`timescale 1ns/1ps
module tb_clock_native;
    reg clk = 0;
    always #7.6923075 clk = !clk;
    reg por_n = 0;
    reg req_valid = 0, req_word = 0, req_write = 0, rsp_ready = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error, fault, boundary;
    wire [15:0] rsp_rdata, cpu_address, capture_address;
    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    wire mem_ready, mem_rsp_valid;
    wire [15:0] mem_rdata;
    card_candidate dut (.*);
    reg [15:0] memory [0:131071];
    reg [7:0] expected [0:262143];
    integer ticks = 0, backend_count = 0, backend_responses = 0, stores = 0;
    integer accepted = 0, responses = 0, posted_acks = 0, early_acks = 0;
    integer stimulus, traces, status, writing, word_access, offset, value, gap;
    integer transaction_count = 0, i, last_capture = 0;
    integer backend_launch = 0, max_backend_latency = 0;
    reg [1023:0] stimulus_path, expected_path, trace_path;
    reg [2:0] phase = 0;
    always @(posedge clk) phase <= phase + 3'd1;
    wire clk8 = phase >= 4;
    reg init = 1, stop_competitors = 0;
    wire adapter_drained, mux_drained;
    wire card_req, card_we, card_ack;
    wire [23:0] card_addr;
    wire [15:0] card_din, card_dout;
    reg floppy_req = 0;
    wire [1:0] client_ack;
    wire [15:0] writeback_dout;
    wire native_req, native_we, native_ack;
    wire [23:0] native_addr;
    wire [15:0] native_din, native_dout;
    assign card_ack = client_ack[0];
    card_native_memory_adapter adapter (
        .clk(clk), .por_n(por_n), .reset_request(1'b0), .drained(adapter_drained),
        .mem_valid(mem_valid), .mem_ready(mem_ready), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata),
        .native_req(card_req), .native_we(card_we), .native_addr(card_addr),
        .native_din(card_din), .native_ack(card_ack), .native_dout(card_dout)
    );
    card_native_port_mux mux (
        .clk(clk), .por_n(por_n), .reset_request(1'b0), .drained(mux_drained),
        .client_req({floppy_req, card_req}), .client_we({1'b0, card_we}),
        .card_addr(card_addr), .floppy_addr(24'h600000), .card_din(card_din),
        .floppy_din(16'b0), .client_ack(client_ack), .card_dout(card_dout),
        .floppy_dout(writeback_dout), .native_req(native_req), .native_we(native_we),
        .native_addr(native_addr), .native_din(native_din),
        .native_ack(native_ack), .native_dout(native_dout)
    );

    reg host_oe = 0, flp_win = 0, flp_guard = 0;
    wire cpu_done;
    wire [15:0] cpu_dout, floppy_dout;
    wire sd_clk, sd_cs, sd_ras, sd_cas, sd_we;
    wire [15:0] sd_data;
    reg [15:0] chip_dout = 0;
    wire [12:0] sd_addr;
    wire [1:0] sd_ba, sd_dqm;
    sdram controller (
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_dout),
        .sd_addr(sd_addr), .sd_dqm(sd_dqm), .sd_ba(sd_ba),
        .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(init), .clk_64(clk), .clk_8(clk8), .din(16'b0), .dout(floppy_dout),
        .addr(24'h000100), .ds(2'b11), .oe(host_oe), .we(1'b0),
        .flp_win(flp_win), .flp_addr(24'h600100), .flp_guard(flp_guard),
        .dl_req(1'b0), .dl_slot(1'b0), .dl_addr(24'b0), .dl_din(16'b0), .dl_ack(),
        .eth_req(native_req), .eth_we(native_we), .eth_addr(native_addr),
        .eth_din(native_din), .eth_ack(native_ack), .eth_dout(native_dout),
        .cpu_done(cpu_done), .cpu_dout(cpu_dout)
    );

    // BL=1/CL=2 command model, not a board or JEDEC timing model.
    reg [11:0] rows [0:3];
    reg [22:0] read_addr, command_addr;
    integer read_delay = 0, refreshes = 0;
    function [15:0] chip_read(input [22:0] address);
        begin
            if (address >= 23'h540000 && address < 23'h560000)
                chip_read = memory[address[16:0]];
            else if (address == 23'h000100) chip_read = 16'hbeef;
            else if (address == 23'h600100) chip_read = 16'hcafe;
            else if (address == 23'h600000) chip_read = 16'hd00d;
            else begin
                $fatal(1, "chip read outside test allocation: %h", address);
                chip_read = 0;
            end
        end
    endfunction
    always @(negedge clk) begin
        if (read_delay > 0) begin
            read_delay = read_delay - 1;
            if (read_delay == 0) chip_dout <= chip_read(read_addr);
        end
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0101: begin
                read_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                read_delay = 2;
            end
            4'b0100: begin
                command_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                if (command_addr < 23'h540000 || command_addr >= 23'h560000)
                    $fatal(1, "write outside test allocation: %h", command_addr);
                if (!controller.src_eth || mux.owner || sd_dqm != 0)
                    $fatal(1, "physical write lost card ownership or word mask");
                if (!sd_dqm[0]) memory[command_addr[16:0]][7:0] = sd_data[7:0];
                if (!sd_dqm[1]) memory[command_addr[16:0]][15:8] = sd_data[15:8];
                stores = stores + 1;
            end
            4'b0001: refreshes = refreshes + 1;
            default: begin end
        endcase
    end

    reg previous_card_ack = 0, held_native = 0;
    reg [40:0] frozen_native;
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 2000000) $fatal(1, "native system watchdog");
        if (por_n && fault) $fatal(1, "candidate fault CPU=%h capture=%h", cpu_address, capture_address);
        if (mem_valid && mem_ready) begin
            backend_count = backend_count + 1;
            backend_launch = ticks;
        end
        if (mem_rsp_valid && mem_rsp_ready) begin
            backend_responses = backend_responses + 1;
            if (card_req || card_ack) $fatal(1, "card response before native rearm");
            if (stores != posted_acks) $fatal(1, "card response before physical commit");
            if (ticks - backend_launch > max_backend_latency)
                max_backend_latency = ticks - backend_launch;
        end
        if (card_ack && !previous_card_ack && card_we) begin
            posted_acks = posted_acks + 1;
            if (stores < posted_acks) early_acks = early_acks + 1;
            else $fatal(1, "native write ACK no longer precedes CAS");
        end
        previous_card_ack = card_ack;
        if (native_req || native_ack) begin
            if (held_native && frozen_native !== {native_we, native_addr, native_din})
                $fatal(1, "native bundle changed before ownership drained");
            frozen_native = {native_we, native_addr, native_din};
            held_native = 1;
        end else held_native = 0;
        if (client_ack == 3) $fatal(1, "native ACK leaked to both clients");
        if (req_valid && req_ready) accepted <= accepted + 1;
        if (rsp_valid && rsp_ready) responses <= responses + 1;
        if (capture_count != last_capture) begin
            if (!capture_valid) $fatal(1, "capture disappeared before observation");
            $fdisplay(traces, "%02x %04x %02x", capture_status, capture_address, capture_data);
            last_capture = capture_count;
        end
    end

    integer host_services = 0, floppy_services = 0, writeback_services = 0;
    initial begin
        wait(por_n);
        while (!stop_competitors) begin
            @(negedge clk); host_oe = 1;
            wait(cpu_done);
            repeat (5) @(posedge clk);
            @(negedge clk);
            if (cpu_dout !== 16'hbeef) $fatal(1, "Macintosh read data corrupted");
            host_services = host_services + 1;
            host_oe = 0;
            repeat (29) @(negedge clk);
        end
    end
    initial begin
        wait(por_n);
        while (!stop_competitors) begin
            @(negedge clk); flp_guard = 1;
            repeat (4) @(negedge clk);
            flp_win = 1;
            wait(controller.flp_served);
            wait(!controller.seq_busy);
            @(negedge clk);
            if (floppy_dout !== 16'hcafe) $fatal(1, "floppy window data corrupted");
            floppy_services = floppy_services + 1;
            flp_win = 0; flp_guard = 0;
            repeat (101) @(negedge clk);
        end
    end
    initial begin
        wait(por_n);
        while (!stop_competitors) begin
            @(negedge clk); floppy_req = 1;
            wait(client_ack[1]);
            @(negedge clk);
            if (writeback_dout !== 16'hd00d) $fatal(1, "floppy writeback data corrupted");
            writeback_services = writeback_services + 1;
            repeat (2) @(negedge clk);
            floppy_req = 0;
            wait(!client_ack[1]);
            repeat (37) @(negedge clk);
        end
    end

    reg [1023:0] latency_path;
    integer latency_file, ordinary_cycles = 0;
    integer launch_cycle, ordinary_count = 0, max_read_cycles = 0, max_write_cycles = 0;
    reg ordinary_pending = 0, pending_write;
    reg [15:0] pending_address;
    real launch_time;
    initial begin
        if (!$value$plusargs("latency=%s", latency_path)) $fatal(1, "missing latency log");
        latency_file = $fopen(latency_path, "w");
    end
    always @(posedge clk) begin
        ordinary_cycles = ordinary_cycles + 1;
        if (dut.runnable && !dut.io_space && !dut.trap && !ordinary_pending) begin
            ordinary_pending = 1;
            launch_cycle = ordinary_cycles - 1;
            launch_time = $realtime - 15.384615;
            pending_address = dut.cpu_address;
            pending_write = dut.cpu_write;
        end
        if (ordinary_pending && dut.cpu_ready) begin
            if (pending_address !== dut.cpu_address || pending_write !== dut.cpu_write)
                $fatal(1, "ordinary CPU cycle changed before completion");
            $fdisplay(latency_file, "%04x %0d %0d %0.3f %0.3f", pending_address, pending_write,
                      ordinary_cycles - launch_cycle, launch_time, $realtime);
            ordinary_count = ordinary_count + 1;
            if (pending_write && ordinary_cycles - launch_cycle > max_write_cycles)
                max_write_cycles = ordinary_cycles - launch_cycle;
            if (!pending_write && ordinary_cycles - launch_cycle > max_read_cycles)
                max_read_cycles = ordinary_cycles - launch_cycle;
            ordinary_pending = 0;
        end
    end

    task transact;
        input integer write_arg, word_arg, offset_arg, value_arg, gap_arg;
        integer n;
        begin
            repeat (gap_arg) @(negedge clk);
            req_valid = 1;
            req_write = write_arg != 0;
            req_word = word_arg != 0;
            req_offset = offset_arg[5:0];
            req_wdata = value_arg[15:0];
            @(posedge clk);
            while (!req_ready) @(posedge clk);
            @(negedge clk);
            req_valid = 0;
            while (!rsp_valid) @(negedge clk);
            if (rsp_error) $fatal(1, "host error offset %h", req_offset);
            if (write_arg == 0 && rsp_rdata !== value_arg[15:0])
                $fatal(1, "host read transaction=%0d offset=%h expected=%h actual=%h CPU=%h capture=%h",
                       transaction_count, req_offset, value_arg[15:0], rsp_rdata, cpu_address, capture_status);
            for (n = 0; n < transaction_count % 4; n = n + 1) begin
                @(negedge clk);
                if (!rsp_valid || (write_arg == 0 && rsp_rdata !== value_arg[15:0]))
                    $fatal(1, "host response unstable");
            end
            rsp_ready = 1;
            @(negedge clk);
            rsp_ready = 0;
            transaction_count = transaction_count + 1;
        end
    endtask

    initial begin
        if (!$value$plusargs("stimulus=%s", stimulus_path)) $fatal(1, "missing stimulus");
        if (!$value$plusargs("expected=%s", expected_path)) $fatal(1, "missing expected");
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1, "missing trace");

        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        $readmemh(expected_path, expected);
        stimulus = $fopen(stimulus_path, "r");
        traces = $fopen(trace_path, "w");
        if (stimulus == 0 || traces == 0) $fatal(1, "file open failed");
        repeat (3) @(negedge clk);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk); por_n = 1;
        @(negedge clk);
        while (!$feof(stimulus)) begin
            status = $fscanf(stimulus, "%d %d %d %d %d\n", writing, word_access, offset, value, gap);
            if (status == 5) transact(writing, word_access, offset, value, gap);
            else if (status != -1) $fatal(1, "bad stimulus");
        end
        repeat (600) @(negedge clk);
        if (!boundary || cpu_address != 16'h202F) $fatal(1, "wrong boundary %h", cpu_address);
        if (capture_valid || capture_count != 39) $fatal(1, "wrong captures %0d", capture_count);
        if (accepted != responses || accepted != transaction_count)
            $fatal(1, "host acceptance/response mismatch");
        if (transaction_count != 1325 || backend_count != 2578 || cpu_completed != 250)
            $fatal(1, "original diagnostic transaction coverage changed");
        stop_competitors = 1;
        wait(!host_oe && !flp_win && !flp_guard && !floppy_req);
        wait(mux_drained && adapter_drained && !controller.seq_busy);
        if (mem_rsp_valid || dut.cpu_memory_wait) $fatal(1, "backend not drained");
        if (backend_count != backend_responses || stores != posted_acks || stores != early_acks)
            $fatal(1, "native completion/commit counts differ");
        if (stores != 1192 || host_services == 0 || floppy_services == 0 || writeback_services == 0 || refreshes <= 8)
            $fatal(1, "native traffic coverage missing");
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "memory mismatch byte %h", i);
        end
        if (dut.processor.cpu.reg_s !== 8'hFD) $fatal(1, "CPU stack not restored");
        $display("PASS host=%0d backend=%0d stores=%0d captures=%0d cpu_cycles=%0d ticks=%0d",
                 transaction_count, backend_count, stores, capture_count, cpu_completed, ticks);
        $display("native commits=%0d early_acks=%0d backend_responses=%0d host=%0d floppy_window=%0d writeback=%0d refresh=%0d max_backend_ticks=%0d", stores, early_acks, backend_responses, host_services, floppy_services, writeback_services, refreshes, max_backend_latency);
        if (ordinary_pending || ordinary_count == 0) $fatal(1, "ordinary latency coverage");
        $display("LATENCY ordinary=%0d max_read_cycles=%0d max_write_cycles=%0d", ordinary_count, max_read_cycles, max_write_cycles);
        $fclose(latency_file);
        $fclose(stimulus);
        $fclose(traces);
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

