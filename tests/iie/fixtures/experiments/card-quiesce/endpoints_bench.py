#!/usr/bin/env python3
"""Retain frozen diagnostic checks while inserting real endpoint warm resets."""

import hashlib

from platform_prepare import ROOT, WORK, replace


def prepare():
    original = ROOT / "fixtures/experiments/card-platform/tb_card_platform.sv"
    source = original.read_text()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == "7c80135c5b3ee037072d469eb53396c4331853e9a886a5bcabe1bb6447179d5e"
    source = replace(source, "    card_platform dut (.*);", """    reg warm_request = 0;
    wire stop_request, stop_mem, controller_quiesce, controller_init;
    wire epoch_reset_sys, epoch_reset_mem, busy, completed;
    wire producers_stopped, source_drained, native_drained, controller_ready_mem, controller_idle;
    integer reset_case = 0, warm_resets = 0, sys_epochs = 0, mem_epochs = 0;
    card_platform dut (.*);
    card_warm_reset sequencer (
        .clk_sys(clk_sys), .clk_mem(clk_mem), .por_n_sys(por_n_sys), .por_n_mem(por_n_mem),
        .warm_request_sys(warm_request), .download_active_sys(1'b0),
        .producers_stopped_sys(producers_stopped), .drained_sys(source_drained),
        .native_drained_mem(native_drained), .controller_ready_mem(controller_ready_mem),
        .controller_idle_mem(controller_idle), .stop_sys(stop_request), .stop_mem(stop_mem),
        .controller_quiesce(controller_quiesce), .controller_init(controller_init),
        .epoch_reset_sys(epoch_reset_sys), .epoch_reset_mem(epoch_reset_mem), .busy(busy), .completed(completed)
    );
    reg previous_init = 0, previous_mem_epoch = 0, previous_sys_epoch = 0;
    always @(posedge clk_mem) begin
        if (controller_init && !previous_init &&
            (!source_drained || !native_drained || stores != posted_acks || !producers_stopped))
            $fatal(1, "reinit before real endpoints drained");
        if (epoch_reset_mem && (native_req || native_ack || stores != posted_acks || !controller_ready_mem))
            $fatal(1, "epoch reset before physical commit/ACK tail");
        previous_init = controller_init;
        if (epoch_reset_mem && !previous_mem_epoch) mem_epochs = mem_epochs + 1;
        previous_mem_epoch = epoch_reset_mem;
        if (completed) warm_resets = warm_resets + 1;
    end
    initial begin
        if (!$value$plusargs("reset_case=%d", reset_case)) reset_case = 0;
        wait(por_n_sys && dut.ready_sync2);
        case (reset_case)
            0: wait(dut.card.req_valid && dut.card.req_offset == 6'h10);
            1: wait(card_ack && card_we);
            2: wait(dut.card.card.cpu_offer_valid);
            3: wait(dut.card.card.cpu_memory_wait);
            4: wait(capture_valid);
            5: wait(floppy_ack);
            6: wait(dut.card.card.memory.state == 3'd2 && dut.card.card.memory.partial_write &&
                    dut.src_rsp_valid);
            default: $fatal(1, "bad reset case");
        endcase
        @(negedge clk_sys); warm_request = 1;
        repeat (2) @(negedge clk_sys);
        warm_request = 0;
    end
    reg held_cpu = 0;
    reg [113:0] frozen_cpu;
    wire [113:0] cpu_snapshot = {cpu_completed, capture_count, capture_valid,
                                capture_status, capture_address, capture_data,
                                dut.card.card.permitted, dut.card.card.cpu_address};
    always @(negedge clk_sys) begin
        if (epoch_reset_sys && !previous_sys_epoch) sys_epochs = sys_epochs + 1;
        previous_sys_epoch = epoch_reset_sys;
        if (dut.cpu_stopped) begin
            if (held_cpu && cpu_snapshot !== frozen_cpu) $fatal(1, "CPU/capture changed while stopped");
            frozen_cpu = cpu_snapshot;
            held_cpu = 1;
        end else held_cpu = 0;
    end""")
    source = replace(source, "    sdram controller (", """    sdram #(.ENABLE_QUIESCE(1)) controller (
        .warm_quiesce(controller_quiesce), .warm_idle(controller_idle), .memory_ready(controller_ready_mem),""")
    source = replace(source, ".init(init),", ".init(init || controller_init),")
    start = source.index("    integer host_services =")
    end = source.index("    reg [15:0] expected_floppy;", start)
    source = source[:start] + "    integer host_services = 0, floppy_services = 0, writeback_services = 0;\n" + source[end:]
    source = replace(source, "        while (!stop_competitors) begin\n            @(negedge clk_sys);", """        while (!stop_competitors) begin
            wait(!stop_request && !busy && dut.ready_sync2);
            @(negedge clk_sys);""")
    source = replace(source, "            wait(dut.floppy_crossing.src_state != 0);", "            wait(dut.floppy_ingress.state != 0);")
    source = replace(source, "repeat (2 + writeback_services % 7)", "repeat (80 + writeback_services % 7)")
    source = replace(source, "            repeat (gap_arg) @(negedge clk_sys);", """            for (n = 0; n < gap_arg; n = n + 1) begin
                @(negedge clk_sys);
                while (stop_request || busy || !dut.ready_sync2) @(negedge clk_sys);
            end
            wait(!stop_request && !busy && dut.ready_sync2);
            @(negedge clk_sys);""")
    source = replace(source, "        wait(controller.reset == 0);\n        @(negedge clk_mem); por_n_mem = 1;", """        @(negedge clk_mem); por_n_mem = 1;""")
    source = replace(source, "        por_n_sys = 1;\n        @(negedge clk_sys);", """        por_n_sys = 1;
        pds_address = 32'h00E0001C; pds_as_n = 0;
        repeat (20) begin
            @(negedge clk_sys);
            if (native_req || dut.card.req_valid || dut.floppy_offer || claim)
                $fatal(1, "request escaped before cold memory readiness");
        end
        pds_as_n = 1;
        wait(dut.ready_sync2 && !stop_request);
        @(negedge clk_sys);""")
    source = replace(source, "        stop_competitors = 1;", """        wait(warm_resets == 1 && !stop_request && !busy);
        stop_competitors = 1;""")
    source = replace(source, "stores != 1192 || host_services == 0 || floppy_services == 0 || writeback_services == 0 || refreshes <= 8", "stores != 1192 || writeback_services == 0 || refreshes <= 8")
    source = replace(source, "        if (mem_rsp_valid || dut.card.card.cpu_memory_wait)", """        @(negedge clk_sys); warm_request = 1;
        repeat (2) @(negedge clk_sys);
        warm_request = 0;
        wait(warm_resets == 2 && !busy && !stop_request);
        @(negedge clk_sys);
        if (sys_epochs != 2 || mem_epochs != 2 ||
            dut.card_crossing.request_toggle || dut.card_crossing.response_toggle ||
            dut.floppy_crossing.request_toggle || dut.floppy_crossing.response_toggle)
            $fatal(1, "repeated reset did not clear both mailbox epochs");
        if (mem_rsp_valid || dut.card.card.cpu_memory_wait)""")
    source = replace(source, "        $fclose(stimulus);", """        if (warm_resets != 2 || dut.card_crossing.request_toggle !== dut.card_crossing.response_toggle ||
            dut.floppy_crossing.request_toggle !== dut.floppy_crossing.response_toggle)
            $fatal(1, "warm reset or mailbox epoch completion missing");
        $display("PASS real-endpoint-warm-reset case=%0d resets=%0d full_memory=262144", reset_case, warm_resets);
        $fclose(stimulus);""")
    output = WORK / "tb_endpoint_platform.sv"
    output.write_text(source, encoding="ascii")
    return output
