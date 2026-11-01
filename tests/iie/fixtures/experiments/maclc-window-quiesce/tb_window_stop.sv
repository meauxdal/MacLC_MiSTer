`timescale 1ns/1ps
`define SOURCE_INPUTS \
    .clk(clk_sys), .ram_config(8'h24), .ram_config_phys(8'h24), .ram_configured(1'b1), \
    ._cpuReset(por_n_sys), .cpuAddr(32'h00800100), ._cpuUDS(1'b1), ._cpuLDS(1'b1), \
    ._cpuRW(1'b1), ._cpuAS(1'b1), .cpuFC(3'b101), .pds_claim(1'b0), \
    .cpu_wr_ack(1'b0), .flp_present(present), .dio_download(download), \
    .words_per_line(11'd320), .dskReadAddrInt(disk_addr), .dskReadAddrExt(22'd0)

module tb_window_stop;
    reg clk_sys = 0, clk_mem = 0;
    always #5 clk_mem = !clk_mem;
    integer phase = 2;
    initial begin
        if (!$value$plusargs("phase=%d", phase)) phase = 2;
        #(phase);
        forever #10 clk_sys = !clk_sys;
    end
    reg por_n_sys = 0, por_n_mem = 0, cold_init = 1;
    reg present = 0, download = 0, manual_stop = 0, warm_request = 0;
    reg [21:0] disk_addr = 22'h000100;
    wire stop_sys, stop_mem, freeze, warm_init, epoch_sys, epoch_mem, busy, completed;
    wire ready, controller_idle, source_stopped, source_drained;
    wire clk8, en_p, en_n, guard, ack, ack_ext;
    wire [22:0] memory_addr;
    wire uds_n, lds_n;
    wire endpoint_stop = manual_stop || stop_sys;
    addrController_top #(.ENABLE_WARM_STOP(1)) dut (
        `SOURCE_INPUTS, .warm_reset(!por_n_sys), .warm_stop(endpoint_stop), .warm_stopped(source_stopped),
        .clk8(clk8), .clk8_en_p(en_p), .clk8_en_n(en_n), .flp_guard(guard),
        .dskReadAckInt(ack), .dskReadAckExt(ack_ext), .memoryAddr(memory_addr),
        ._memoryUDS(uds_n), ._memoryLDS(lds_n)
    );
    wire baseline_ack, baseline_guard, baseline_uds, baseline_lds;
    wire [22:0] baseline_addr;
    baseline_addrController_top baseline (
        `SOURCE_INPUTS, .dskReadAckInt(baseline_ack), .flp_guard(baseline_guard),
        .memoryAddr(baseline_addr), ._memoryUDS(baseline_uds), ._memoryLDS(baseline_lds)
    );
    wire default_ack, default_guard, default_uds, default_lds;
    wire [22:0] default_addr;
    addrController_top default_off (
        `SOURCE_INPUTS, .warm_reset(!por_n_sys), .warm_stop(endpoint_stop), .warm_stopped(),
        .dskReadAckInt(default_ack), .flp_guard(default_guard),
        .memoryAddr(default_addr), ._memoryUDS(default_uds), ._memoryLDS(default_lds)
    );

    // Same mixed-stage window/guard and byte parity paths as MacLC.sv.
    reg guard_q, odd_q;
    always @(posedge clk_sys) begin
        guard_q <= guard && !download;
        odd_q <= disk_addr[0];
    end
    wire [15:0] floppy_word;
    wire [7:0] floppy_byte = odd_q ? floppy_word[7:0] : floppy_word[15:8];
    wire ack_delayed;
    wire [7:0] latched_byte;
    floppy_read_tail consumer (
        .clk(clk_sys), .cen(en_n), .cep(en_p), .dskReadAck(ack), .dskReadData(floppy_byte),
        .dskReadAckD(ack_delayed), .dskReadDataLatch(latched_byte)
    );
    assign source_drained = source_stopped && !guard && !guard_q && !ack && !ack_delayed;
    card_warm_reset sequencer (
        .clk_sys(clk_sys), .clk_mem(clk_mem), .por_n_sys(por_n_sys), .por_n_mem(por_n_mem),
        .warm_request_sys(warm_request), .download_active_sys(download),
        .producers_stopped_sys(source_stopped), .drained_sys(source_drained),
        .native_drained_mem(1'b1), .controller_ready_mem(ready), .controller_idle_mem(controller_idle),
        .stop_sys(stop_sys), .stop_mem(stop_mem), .controller_quiesce(freeze), .controller_init(warm_init),
        .epoch_reset_sys(epoch_sys), .epoch_reset_mem(epoch_mem), .busy(busy), .completed(completed)
    );
    wire sd_clk, sd_cs, sd_ras, sd_cas, sd_we;
    wire [15:0] sd_data;
    reg [15:0] chip_data = 0;
    wire [12:0] sd_addr;
    wire [1:0] sd_ba, sd_dqm;
    sdram #(.ENABLE_QUIESCE(1)) controller (
        .warm_quiesce(freeze), .warm_idle(controller_idle), .memory_ready(ready),
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_data), .sd_addr(sd_addr),
        .sd_dqm(sd_dqm), .sd_ba(sd_ba), .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(cold_init || warm_init), .clk_64(clk_mem), .clk_8(clk8),
        .din(16'd0), .dout(floppy_word), .addr(24'd0), .ds(2'b11), .oe(1'b0), .we(1'b0),
        .flp_win(ack && !download), .flp_addr({1'b0, memory_addr}), .flp_guard(guard_q),
        .dl_req(1'b0), .dl_slot(1'b0), .dl_addr(24'd0), .dl_din(16'd0), .dl_ack(),
        .eth_req(1'b0), .eth_we(1'b0), .eth_addr(24'd0), .eth_din(16'd0), .eth_ack(),
        .eth_dout(), .cpu_done(), .cpu_dout()
    );
    function [15:0] chip_read(input [22:0] address);
        chip_read = 16'h5aa5 ^ address[15:0];
    endfunction
    reg [11:0] rows [0:3];
    reg [22:0] read_addr;
    integer read_delay = 0, physical_reads = 0, windows = 0, resets = 0, ticks = 0, window_ticks = 0;
    reg old_ack = 0, old_init = 0, previous_idle = 0;
    always @(negedge clk_mem) begin
        if (read_delay > 0) begin
            read_delay = read_delay - 1;
            if (read_delay == 0) chip_data <= chip_read(read_addr);
        end
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0101: begin
                read_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                if (read_addr < 23'h600000)
                    $fatal(1, "wrong floppy address %h mux=%h ack=%b guard=%b", read_addr, memory_addr, ack, guard);
                physical_reads = physical_reads + 1;
                read_delay = 2;
            end
            4'b0100: $fatal(1, "unexpected write");
            default: begin end
        endcase
    end
    always @(posedge clk_mem) begin
        ticks = ticks + 1;
        if (ticks > 160000) $fatal(1, "window watchdog case=%d state=%d", test_case, sequencer.state);
        if (warm_init && !old_init && (!source_drained || !previous_idle || controller.flp_cap || read_delay != 0))
            $fatal(1, "reinit before window/consumer/capture drained");
        if (completed) resets = resets + 1;
        old_init = warm_init;
        previous_idle = controller_idle;
    end
    always @(negedge clk_sys) begin
        if (ack && !old_ack) windows = windows + 1;
        if (ack) window_ticks = window_ticks + 1;
        else if (old_ack) begin
            if (window_ticks != 4) $fatal(1, "TRUNCATED_WINDOW ticks=%0d", window_ticks);
            window_ticks = 0;
        end
        old_ack = ack;
        if ({default_ack, default_guard, default_addr, default_uds, default_lds} !==
            {baseline_ack, baseline_guard, baseline_addr, baseline_uds, baseline_lds})
            $fatal(1, "default-off behavior changed");
        if (por_n_sys && source_stopped && (ack || guard || memory_addr != 0 || !uds_n || !lds_n))
            $fatal(1, "stopped window retained floppy address or strobes");
    end
    task check_delivery;
        integer before_windows;
        reg [15:0] expected_word;
        begin
            before_windows = windows;
            wait(windows >= before_windows + 3);
            wait(!ack && !ack_delayed && !controller.seq_busy);
            @(negedge clk_sys);
            expected_word = chip_read(23'h600000 + {2'b0, disk_addr[21:1]});
            if (latched_byte !== (disk_addr[0] ? expected_word[7:0] : expected_word[15:8]))
                $fatal(1, "floppy byte delivery addr=%h actual=%h expected_word=%h", disk_addr, latched_byte, expected_word);
        end
    endtask
    integer test_case, before_resets, before_reads, i;
    initial begin
        // The original slot counters have no reset; select a finite test phase.
        dut.busPhase = 0; dut.busCycle = 0; dut.extra_slot_count = 0; dut.extra_slot_advance = 0;
        baseline.busPhase = 0; baseline.busCycle = 0; baseline.extra_slot_count = 0; baseline.extra_slot_advance = 0;
        default_off.busPhase = 0; default_off.busCycle = 0; default_off.extra_slot_count = 0; default_off.extra_slot_advance = 0;
        repeat (4) @(negedge clk_mem);
        cold_init = 0;
        wait(ready);
        @(negedge clk_mem); por_n_mem = 1;
        @(negedge clk_sys); por_n_sys = 1;
        wait(!stop_sys);
        wait(!guard && !ack);
        present = 1;
        for (test_case = 0; test_case < 8; test_case = test_case + 1) begin
            check_delivery;
            case (test_case)
                0: wait(!guard && !ack);
                1: wait(guard && !ack);
                2, 3, 4, 5: wait(ack && dut.busPhase == 2'(test_case - 2));
                6: wait(controller.flp_cap);
                7: wait(!ack && ack_delayed);
            endcase
            @(negedge clk_sys); manual_stop = 1;
            before_resets = resets;
            wait(source_drained);
            @(negedge clk_sys); warm_request = 1;
            repeat (2) @(negedge clk_sys);
            warm_request = 0;
            wait(resets > before_resets && !busy && !stop_sys);
            before_reads = physical_reads;
            for (i = 0; i < 12; i = i + 1) begin
                @(negedge clk_sys);
                if (!source_drained || ack_delayed || physical_reads != before_reads)
                    $fatal(1, "new window/capture escaped stopped source");
            end
            if (windows != physical_reads) $fatal(1, "window lost or duplicated windows=%0d reads=%0d", windows, physical_reads);
            disk_addr = disk_addr + 22'd3;
            manual_stop = 0;
        end
        check_delivery;
        @(negedge clk_sys); manual_stop = 1;
        wait(source_drained && !controller.seq_busy && !controller.flp_cap);
        if (resets != 8 || windows != physical_reads) $fatal(1, "final accounting mismatch");
        $display("PASS window-stop phase=%0d resets=%0d windows=%0d physical_reads=%0d parity-delivery default-off", phase, resets, windows, physical_reads);
        $finish;
    end
endmodule

module altddio_out #(
    parameter extend_oe_disable = "OFF", intended_device_family = "Cyclone V",
              invert_output = "OFF", lpm_hint = "UNUSED", lpm_type = "altddio_out",
              oe_reg = "UNREGISTERED", power_up_high = "OFF", width = 1
) (
    input wire [width-1:0] datain_h, datain_l,
    input wire outclock, aclr, aset, oe, outclocken, sclr, sset,
    output wire [width-1:0] dataout
);
    assign dataout = outclock ? datain_h : datain_l;
endmodule
