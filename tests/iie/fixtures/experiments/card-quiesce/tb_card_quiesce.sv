`timescale 1ns/1ps
module tb_card_quiesce;
    parameter NEGATIVE_CONTROL = 0;
    reg clk_sys = 0, clk_mem = 0;
    always #7 clk_sys = !clk_sys;
    always #5 clk_mem = !clk_mem;
    reg por_n_sys = 0, por_n_mem = 0, cold_init = 1, immediate_init = 0, probe_freeze = 0;
    reg warm_request = 0, download_active = 0;
    wire stop_sys, stop_mem, freeze, warm_init, epoch_sys, epoch_mem, busy, completed;
    wire memory_ready, controller_idle, source_drained, native_drained;
    reg req_valid = 0, req_word = 1, rsp_ready = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error;
    wire [15:0] rsp_rdata;
    wire [7:0] control;
    wire [15:0] index;
    wire [1:0] master_valid, master_ready, master_write, master_response, master_rsp_ready;
    wire [17:0] host_addr;
    wire [15:0] host_wdata, master_rdata;
    wire [1:0] host_be;
    wire host_rsp_ready, arb_drained, denied;
    reg cpu_offer = 0, cpu_wait = 0;
    reg [17:0] cpu_addr = 0;
    reg [15:0] cpu_data = 0;
    wire sys_reset = !por_n_sys || epoch_sys;
    assign master_valid[1] = cpu_offer;
    assign master_write[1] = 1;
    assign master_rsp_ready = {cpu_wait, host_rsp_ready};
    card_host_registers host (
        .clk(clk_sys), .reset(sys_reset), .req_valid(req_valid), .req_ready(req_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(1'b1), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_req_valid(master_valid[0]), .mem_req_ready(master_ready[0]),
        .mem_req_addr(host_addr), .mem_req_write(master_write[0]), .mem_req_wdata(host_wdata), .mem_req_be(host_be),
        .mem_rsp_valid(master_response[0]), .mem_rsp_ready(host_rsp_ready),
        .mem_rsp_rdata(master_rdata), .mem_rsp_denied(denied), .control(control), .index(index),
        .capture_status(8'b0), .capture_address(16'b0), .capture_data(8'b0),
        .keyboard_status(8'b0), .opaque08(8'b0), .sidefx_valid(), .sidefx_offset(),
        .sidefx_word(), .sidefx_write(), .sidefx_wdata(), .ack_write(), .read_release_write(),
        .capture_address_read(), .control_write(), .command_write(), .mask_write(), .keyboard_write()
    );
    wire mem_valid, mem_ready, mem_write, mem_response, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata, mem_rdata;
    // An accepted host word may still offer its second lane after stop_sys.
    wire host_idle = host.state == 0 && !req_valid;
    card_memory_arbiter arb (
        .clk(clk_sys), .por_n(!sys_reset), .reset_request(stop_sys && host_idle && !cpu_offer),
        .drained(arb_drained), .req_valid(master_valid), .req_ready(master_ready),
        .req_write(master_write), .req_write_allowed(2'b11),
        .host_addr(host_addr), .card_addr(cpu_addr), .host_wdata(host_wdata), .card_wdata(cpu_data),
        .host_be(host_be), .card_be(2'b10), .rsp_valid(master_response), .rsp_ready(master_rsp_ready),
        .rsp_rdata(master_rdata), .rsp_denied(denied), .mem_valid(mem_valid), .mem_ready(mem_ready),
        .mem_write(mem_write), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
        .mem_rsp_valid(mem_response), .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata)
    );
    wire dst_valid, dst_ready, dst_write, dst_response, dst_rsp_ready, card_cdc_drained;
    wire [16:0] dst_addr;
    wire [15:0] dst_wdata, dst_rdata;
    card_memory_cdc crossing (
        .src_clk(clk_sys), .src_reset(sys_reset), .dst_clk(clk_mem), .dst_reset(!por_n_mem || epoch_mem),
        .src_valid(mem_valid), .src_ready(mem_ready), .src_write(mem_write),
        .src_addr(mem_addr), .src_wdata(mem_wdata), .src_rsp_valid(mem_response),
        .src_rsp_ready(mem_rsp_ready), .src_rdata(mem_rdata), .drained(card_cdc_drained),
        .dst_valid(dst_valid), .dst_ready(dst_ready), .dst_write(dst_write),
        .dst_addr(dst_addr), .dst_wdata(dst_wdata), .dst_rsp_valid(dst_response),
        .dst_rsp_ready(dst_rsp_ready), .dst_rdata(dst_rdata)
    );
    wire card_req, card_we, card_ack, adapter_drained;
    wire [23:0] card_addr;
    wire [15:0] card_din, card_dout;
    card_native_memory_adapter adapter (
        .clk(clk_mem), .por_n(por_n_mem && !epoch_mem), .reset_request(freeze), .drained(adapter_drained),
        .mem_valid(dst_valid), .mem_ready(dst_ready), .mem_write(dst_write),
        .mem_addr(dst_addr), .mem_wdata(dst_wdata), .mem_rsp_valid(dst_response),
        .mem_rsp_ready(dst_rsp_ready), .mem_rdata(dst_rdata), .native_req(card_req),
        .native_we(card_we), .native_addr(card_addr), .native_din(card_din),
        .native_ack(card_ack), .native_dout(card_dout)
    );
    reg floppy_req = 0;
    wire floppy_ack, floppy_cdc_drained, floppy_dst_valid, floppy_dst_ready;
    wire floppy_rsp_valid, floppy_rsp_ready;
    wire [23:0] floppy_dst_addr;
    wire [15:0] floppy_data;
    reg floppy_active = 0, floppy_response = 0;
    reg [23:0] floppy_addr = 0;
    reg [15:0] floppy_frozen_data = 0;
    wire [15:0] floppy_native_data;
    wire [1:0] client_ack;
    card_memory_cdc #(.ADDR_WIDTH(24)) floppy_crossing (
        .src_clk(clk_sys), .src_reset(sys_reset), .dst_clk(clk_mem), .dst_reset(!por_n_mem || epoch_mem),
        .src_valid(floppy_req), .src_ready(), .src_write(1'b0), .src_addr(24'h600000), .src_wdata(16'b0),
        .src_rsp_valid(floppy_ack), .src_rsp_ready(!floppy_req), .src_rdata(floppy_data),
        .drained(floppy_cdc_drained), .dst_valid(floppy_dst_valid), .dst_ready(floppy_dst_ready),
        .dst_write(), .dst_addr(floppy_dst_addr), .dst_wdata(),
        .dst_rsp_valid(floppy_response), .dst_rsp_ready(floppy_rsp_ready), .dst_rdata(floppy_frozen_data)
    );
    assign floppy_dst_ready = !floppy_active && !floppy_response && !client_ack[1];
    always @(posedge clk_mem) begin
        if (!por_n_mem || epoch_mem) begin
            floppy_active <= 0;
            floppy_response <= 0;
            floppy_addr <= 0;
            floppy_frozen_data <= 0;
        end else begin
            if (floppy_dst_valid && floppy_dst_ready) begin
                floppy_addr <= floppy_dst_addr;
                floppy_active <= 1;
            end
            if (floppy_active && client_ack[1]) begin
                floppy_active <= 0;
                floppy_frozen_data <= floppy_native_data;
                floppy_response <= 1;
            end
            if (floppy_response && floppy_rsp_ready) floppy_response <= 0;
        end
    end
    wire native_req, native_we, native_ack, mux_drained;
    wire [23:0] native_addr;
    wire [15:0] native_din, native_dout;
    assign card_ack = client_ack[0];
    card_native_port_mux ownership (
        .clk(clk_mem), .por_n(por_n_mem && !epoch_mem), .reset_request(freeze), .drained(mux_drained),
        .client_req({floppy_active, card_req}), .client_we({1'b0, card_we}),
        .card_addr(card_addr), .floppy_addr(floppy_addr), .card_din(card_din), .floppy_din(16'b0),
        .client_ack(client_ack), .card_dout(card_dout), .floppy_dout(floppy_native_data),
        .native_req(native_req), .native_we(native_we), .native_addr(native_addr),
        .native_din(native_din), .native_ack(native_ack), .native_dout(native_dout)
    );
    assign source_drained = host_idle && !cpu_offer && !cpu_wait && arb_drained &&
                            card_cdc_drained && floppy_cdc_drained && !floppy_req;
    assign native_drained = adapter_drained && mux_drained && !floppy_active && !floppy_response && !dst_valid;
    card_warm_reset sequencer (
        .clk_sys(clk_sys), .clk_mem(clk_mem), .por_n_sys(por_n_sys), .por_n_mem(por_n_mem),
        .warm_request_sys(warm_request), .download_active_sys(download_active),
        .producers_stopped_sys(stop_sys && !req_valid && !cpu_offer && !floppy_req),
        .drained_sys(source_drained), .native_drained_mem(native_drained),
        .controller_ready_mem(memory_ready), .controller_idle_mem(controller_idle),
        .stop_sys(stop_sys), .stop_mem(stop_mem), .controller_quiesce(freeze), .controller_init(warm_init),
        .epoch_reset_sys(epoch_sys), .epoch_reset_mem(epoch_mem), .busy(busy), .completed(completed)
    );

    reg [2:0] phase = 0;
    always @(posedge clk_mem) phase <= phase + 3'd1;
    wire sd_clk, sd_cs, sd_ras, sd_cas, sd_we;
    wire [15:0] sd_data;
    reg [15:0] chip_data = 0;
    wire [12:0] sd_addr;
    wire [1:0] sd_ba, sd_dqm;
    sdram #(.ENABLE_QUIESCE(1)
`ifdef HAS_OPT_NATIVE
        , .NATIVE_BYTE_ENABLE(1), .FAIR_NATIVE_ADMISSION(1)
`endif
    ) controller (
        .warm_quiesce(freeze || probe_freeze), .warm_idle(controller_idle), .memory_ready(memory_ready),
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_data), .sd_addr(sd_addr),
        .sd_dqm(sd_dqm), .sd_ba(sd_ba), .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(cold_init || warm_init || immediate_init), .clk_64(clk_mem), .clk_8(phase >= 4),
        .din(16'b0), .dout(), .addr(24'b0), .ds(2'b11), .oe(1'b0), .we(1'b0),
        .flp_win(1'b0), .flp_addr(24'b0), .flp_guard(1'b0),
        .dl_req(1'b0), .dl_slot(1'b0), .dl_addr(24'b0), .dl_din(16'b0), .dl_ack(),
        .eth_req(native_req), .eth_we(native_we), .eth_addr(native_addr), .eth_din(native_din),
`ifdef HAS_OPT_NATIVE
        .eth_ds(2'b11),
`endif
        .eth_ack(native_ack), .eth_dout(native_dout), .cpu_done(), .cpu_dout()
    );
    reg [15:0] memory [0:131071], reference_memory [0:131071];
    reg [11:0] rows [0:3];
    reg [22:0] read_address, chip_address;
    integer read_delay = 0, stores = 0, posted = 0, refreshes = 0;
    integer ticks = 0, resets = 0, host_accepts = 0, host_responses = 0, cpu_accepts = 0;
    integer backend_accepts = 0, backend_responses = 0;
    integer epoch_mem_count = 0, epoch_sys_count = 0;
    reg previous_card_ack = 0, previous_warm_init = 0, previous_controller_idle = 0;
    reg previous_epoch_mem = 0, previous_epoch_sys = 0;
    always @(negedge clk_mem) begin
        if (read_delay > 0) begin
            read_delay = read_delay - 1;
            if (read_delay == 0) begin
                if (read_address >= 23'h540000 && read_address < 23'h560000)
                    chip_data <= memory[read_address[16:0]];
                else if (read_address == 23'h600000) chip_data <= 16'hcafe;
                else $fatal(1, "unallocated read %h", read_address);
            end
        end
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0101: begin
                read_address = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                read_delay = 2;
            end
            4'b0100: begin
                chip_address = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                if (chip_address < 23'h540000 || chip_address >= 23'h560000 || sd_dqm != 0)
                    $fatal(1, "invalid committed write %h", chip_address);
                memory[chip_address[16:0]] = sd_data;
                stores = stores + 1;
            end
            4'b0001: refreshes = refreshes + 1;
            default: begin end
        endcase
    end
    always @(posedge clk_mem) begin
        ticks = ticks + 1;
        if (ticks > 150000) $fatal(1, "quiesce watchdog state=%0d source=%b native=%b host=%0d cpu=%b%b cdc=%b%b floppy=%b reset=%0d stores=%0d posted=%0d arb=%0d", sequencer.state, source_drained, native_drained, host.state, cpu_offer, cpu_wait, card_cdc_drained, floppy_cdc_drained, floppy_req, controller.reset, stores, posted, arb.state);
        if (card_ack && !previous_card_ack && card_we) posted = posted + 1;
        previous_card_ack = card_ack;
        if (warm_init && !previous_warm_init) begin
            if (!native_drained || !source_drained || !previous_controller_idle || download_active || posted != stores)
                $fatal(1, "reinit before accepted work committed and drained");
        end
        if (epoch_mem && (native_req || native_ack || !memory_ready || posted != stores))
            $fatal(1, "mailbox epoch reset before backend quiescence");
        previous_warm_init = warm_init;
        previous_controller_idle = controller_idle;
        if (epoch_mem && !previous_epoch_mem) epoch_mem_count = epoch_mem_count + 1;
        previous_epoch_mem = epoch_mem;
        if (completed) resets = resets + 1;
    end
    always @(posedge clk_sys) begin
        if (req_valid && req_ready) host_accepts = host_accepts + 1;
        if (rsp_valid && rsp_ready) host_responses = host_responses + 1;
        if (cpu_offer && master_ready[1]) cpu_accepts = cpu_accepts + 1;
        if (mem_valid && mem_ready) backend_accepts = backend_accepts + 1;
        if (mem_response && mem_rsp_ready) backend_responses = backend_responses + 1;
        if (epoch_sys && !previous_epoch_sys) epoch_sys_count = epoch_sys_count + 1;
        previous_epoch_sys = epoch_sys;
    end
    task automatic host_transaction(input [5:0] offset, input [15:0] value, input integer hold_cycles);
        begin
            @(negedge clk_sys);
            if (stop_sys) $fatal(1, "new host transaction while stopped");
            req_offset = offset; req_wdata = value; req_valid = 1;
            do @(posedge clk_sys); while (!req_ready);
            @(negedge clk_sys); req_valid = 0;
            wait(rsp_valid);
            repeat (hold_cycles) begin
                @(negedge clk_sys);
                if (warm_init || epoch_sys || !rsp_valid) $fatal(1, "held host response canceled by reset");
            end
            if (rsp_error) $fatal(1, "host transaction denied");
            rsp_ready = 1;
            @(negedge clk_sys); rsp_ready = 0;
        end
    endtask
    task automatic cpu_transaction(input [17:0] address, input [7:0] value);
        begin
            wait(master_valid[0]);
            @(negedge clk_sys);
            cpu_addr = address; cpu_data = {value, value}; cpu_offer = 1;
            do @(posedge clk_sys); while (!master_ready[1]);
            @(negedge clk_sys); cpu_offer = 0; cpu_wait = 1;
            wait(master_response[1]);
            @(posedge clk_sys);
            @(negedge clk_sys); cpu_wait = 0;
        end
    endtask
    task automatic floppy_transaction;
        begin
            @(negedge clk_sys); floppy_req = 1;
            wait(floppy_ack);
            repeat (80) begin
                @(negedge clk_sys);
                if (floppy_data !== 16'hcafe || !floppy_ack || epoch_sys || warm_init)
                    $fatal(1, "held floppy response lost during stop");
            end
            floppy_req = 0;
            wait(!floppy_ack);
        end
    endtask
    task automatic pulse_warm;
        begin
            @(negedge clk_sys); warm_request = 1;
            repeat (2) @(negedge clk_sys);
            warm_request = 0;
        end
    endtask

    integer i, case_number, resets_before;
    initial begin
        for (i = 0; i < 131072; i = i + 1) begin memory[i] = 16'h5aa5; reference_memory[i] = 16'h5aa5; end
        repeat (4) @(negedge clk_mem);
        cold_init = 0;
        wait(memory_ready);
        wait(controller.ref_busy);
        @(negedge clk_mem); probe_freeze = 1;
        if (controller_idle) $fatal(1, "refresh pipeline reported idle early");
        wait(!controller.ref_busy);
        @(negedge clk_mem);
        if (!controller_idle) $fatal(1, "controller did not drain refresh under freeze");
        repeat (10) @(negedge clk_mem);
        probe_freeze = 0;
        @(negedge clk_mem); por_n_mem = 1;
        @(negedge clk_sys); por_n_sys = 1;
        wait(!stop_sys);
        for (case_number = 0; case_number < 5; case_number = case_number + 1) begin
            host_transaction(6'h1c, 16'h0100 + 16'(case_number * 2), 1);
            reference_memory[128 + case_number][7:0] = 8'h12;
            reference_memory[32896 + case_number][7:0] = 8'h34 + 8'(case_number);
            reference_memory[254 + case_number][15:8] = 8'hd0 + 8'(case_number);
            resets_before = resets;
            download_active = case_number == 4;
            fork
                host_transaction(6'h10, 16'h1234 + 16'(case_number), 50);
                cpu_transaction(18'h001fd + 18'(case_number * 2), 8'hd0 + 8'(case_number));
                floppy_transaction();
                begin
                    if (case_number == 1) wait(mem_response && arb.state == 3'd2);
                    else if (case_number == 2) wait(rsp_valid);
                    else if (case_number == 3) wait(floppy_ack);
                    else wait(card_ack && card_we);
                    if (NEGATIVE_CONTROL) begin
                        @(negedge clk_mem); immediate_init = 1;
                        repeat (20) @(negedge clk_mem);
                        if (posted == 0 || stores >= posted) $fatal(1, "immediate init failed to expose posted-write cancellation");
                        $display("EXPECTED_CANCELED_POSTED_WRITE posted=%0d committed=%0d", posted, stores);
                        $finish;
                    end
                    if (case_number == 0) begin
                        probe_freeze = 1;
                        fork
                            pulse_warm();
                            begin
                                repeat (12) @(negedge clk_mem);
                                if (stores == 0) $fatal(1, "admission freeze canceled accepted write");
                                probe_freeze = 0;
                            end
                        join
                    end else pulse_warm();
                    if (case_number == 4) begin
                        repeat (20) begin
                            @(negedge clk_sys);
                            if (stop_sys || warm_init || epoch_sys) $fatal(1, "warm reset started during active download");
                        end
                        download_active = 0;
                    end
                end
            join
            wait(resets > resets_before);
            wait(!stop_sys && !epoch_sys && !busy);
            @(negedge clk_sys);
            if (!source_drained || !native_drained || index != 0 || stores != (case_number + 1) * 3)
                $fatal(1, "warm reset failed to drain/rearm endpoint");
            if (crossing.request_toggle || crossing.response_toggle ||
                floppy_crossing.request_toggle || floppy_crossing.response_toggle)
                $fatal(1, "mailbox epochs were not reset in both domains");
            for (i = 0; i < 131072; i = i + 1)
                if (memory[i] !== reference_memory[i]) $fatal(1, "memory changed across reset word=%h actual=%h expected=%h", i, memory[i], reference_memory[i]);
        end
        if (host_accepts != 10 || host_responses != 10 || cpu_accepts != 5 || backend_accepts != 30 || backend_responses != 30)
            $fatal(1, "accepted work count changed");
        if (epoch_mem_count != 5 || epoch_sys_count != 5) $fatal(1, "mailbox reset handshake missing");
        $display("PASS coordinated-quiesce resets=%0d host=%0d/%0d CPU=%0d backend=%0d/%0d posted=%0d committed=%0d refresh=%0d ticks=%0d",
                 resets, host_accepts, host_responses, cpu_accepts, backend_accepts, backend_responses, posted, stores, refreshes, ticks);
        $display("mailbox epoch resets sys=%0d mem=%0d", epoch_sys_count, epoch_mem_count);
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
