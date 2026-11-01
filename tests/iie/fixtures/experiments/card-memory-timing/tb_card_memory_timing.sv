`timescale 1ns/1ps
`ifdef BACKEND_PATH
`define PLATFORM card_platform
`define CORE dut.card.card
`define PDS dut.card.pds
`define CROSS_DRAIN dut.card_crossing.drained
`define REQ_VALID dut.card.req_valid
`define REQ_READY dut.card.req_ready
`define RSP_VALID dut.card.rsp_valid
`define RSP_READY dut.card.rsp_ready
`define CPU_CLOCK clk_sys
`define CPU_PERIOD 30.76923
`else
`ifdef BYTE_PATH
`define PLATFORM card_byte_frontend_platform
`else
`define PLATFORM card_frontend_platform
`endif
`define CORE dut.card
`define PDS dut.pds
`define CROSS_DRAIN dut.host_crossing.drained
`define REQ_VALID dut.pds_req_valid
`define REQ_READY dut.pds_req_ready
`define RSP_VALID dut.pds_rsp_valid
`define RSP_READY dut.pds_rsp_ready
`define CPU_CLOCK clk_mem
`define CPU_PERIOD 15.384615
`endif

module tb_card_memory_timing #(
    parameter FAIR = 0,
    parameter BYTE_ENABLE = 0
);
    reg clk_sys = 0, clk_mem = 0;
    real sys_half = 15.384615, sys_phase = 1.25;
    always #7.6923075 clk_mem = !clk_mem;
    initial begin
        if (!$value$plusargs("sys_half=%f", sys_half)) sys_half = 15.384615;
        if (!$value$plusargs("sys_phase=%f", sys_phase)) sys_phase = 1.25;
        #(sys_phase);
        forever #(sys_half) clk_sys = !clk_sys;
    end
    reg por_n_mem = 0;
    reg por_n_sys = 0;
    reg host_reset = 0;
    reg [31:0] pds_address = 0;
    reg [2:0] pds_fc = 3'b001;
    reg pds_as_n = 1, pds_uds_n = 1, pds_lds_n = 1, pds_rw = 1;
    reg [15:0] pds_write_data = 0;
    wire claim, dtack_n, error, fault, boundary;
    wire [15:0] pds_read_data, card_cpu_address, capture_address;
    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    wire native_req, native_we, native_ack;
    wire [23:0] native_addr;
    wire [15:0] native_din, native_dout;
    reg floppy_req = 0;
    reg [23:0] floppy_addr = 24'h600000;
    wire floppy_ack;
    wire [15:0] floppy_data;
    `PLATFORM dut (.*);
`ifdef BYTE_PATH
    wire [1:0] native_ds;
`else
    wire [1:0] native_ds = 2'b11;
`endif
    reg [15:0] memory [0:131071];
    reg [7:0] expected [0:262143];
    integer ticks = 0, mem_ticks = 0, backend_count = 0, backend_responses = 0, stores = 0;
    integer accepted = 0, responses = 0, posted_acks = 0, early_acks = 0;
    integer stimulus, traces, status, writing, word_access, offset, value, gap;
    integer transaction_count = 0, i, last_capture = 0;
    integer backend_launch = 0, max_backend_latency = 0;
    reg [1023:0] stimulus_path, expected_path, trace_path;
    reg [2:0] phase = 0;
    always @(posedge clk_mem) phase <= phase + 3'd1;
    wire clk8 = phase >= 4;
    reg init = 1, stop_competitors = 0;
    wire card_req = dut.card_req;
    wire card_we = dut.card_we;
    wire card_ack = dut.client_ack[0];
    wire [1:0] client_ack = dut.client_ack;
    wire mem_valid = dut.dst_valid;
    wire mem_ready = dut.dst_ready;
    wire mem_rsp_valid = dut.dst_rsp_valid;
    wire mem_rsp_ready = dut.dst_rsp_ready;
    reg host_oe = 0, flp_win = 0, flp_guard = 0;
    wire cpu_done;
    wire [15:0] cpu_dout, floppy_dout;
    wire sd_clk, sd_cs, sd_ras, sd_cas, sd_we;
    wire [15:0] sd_data;
    reg [15:0] chip_dout = 0;
    wire [12:0] sd_addr;
    wire [1:0] sd_ba, sd_dqm;
    sdram #(.FAIR_NATIVE_ADMISSION(FAIR), .NATIVE_BYTE_ENABLE(BYTE_ENABLE)) controller (
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_dout),
        .sd_addr(sd_addr), .sd_dqm(sd_dqm), .sd_ba(sd_ba),
        .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(init), .clk_64(clk_mem), .clk_8(clk8), .din(16'b0), .dout(floppy_dout),
        .addr(24'h000100), .ds(2'b11), .oe(host_oe), .we(1'b0),
        .flp_win(flp_win), .flp_addr(24'h600100), .flp_guard(flp_guard),
        .dl_req(1'b0), .dl_slot(1'b0), .dl_addr(24'b0), .dl_din(16'b0), .dl_ack(),
        .eth_req(native_req), .eth_we(native_we), .eth_ds(native_ds), .eth_addr(native_addr),
        .eth_din(native_din), .eth_ack(native_ack), .eth_dout(native_dout),
        .cpu_done(cpu_done), .cpu_dout(cpu_dout)
    );

    // BL=1/CL=2 command model, not a board or JEDEC timing model.
    reg [11:0] rows [0:3];
    reg [22:0] read_addr, command_addr;
    integer read_delay = 0, refreshes = 0, writeback_reads = 0;
    function [15:0] chip_read(input [22:0] address);
        begin
            if (address >= 23'h540000 && address < 23'h560000)
                chip_read = memory[address[16:0]];
            else if (address == 23'h000100) chip_read = 16'hbeef;
            else if (address == 23'h600100) chip_read = 16'hcafe;
            else if (address == 23'h600000) chip_read = 16'hd00d;
            else if (address == 23'h600002) chip_read = 16'h0df0;
            else begin
                $fatal(1, "chip read outside test allocation: %h", address);
                chip_read = 0;
            end
        end
    endfunction
    always @(negedge clk_mem) begin
        if (read_delay > 0) begin
            read_delay = read_delay - 1;
            if (read_delay == 0) chip_dout <= chip_read(read_addr);
        end
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0101: begin
                read_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                read_delay = 2;
                if (controller.src_eth && dut.ownership.owner) writeback_reads = writeback_reads + 1;
            end
            4'b0100: begin
                command_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                if (command_addr < 23'h540000 || command_addr >= 23'h560000)
                    $fatal(1, "write outside test allocation: %h", command_addr);
                if (!controller.src_eth || dut.ownership.owner || sd_dqm !== ~native_ds)
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
    always @(posedge clk_mem) begin
        mem_ticks = mem_ticks + 1;
        if (por_n_mem && fault) $fatal(1, "candidate fault CPU=%h capture=%h", card_cpu_address, capture_address);
        if (mem_valid && mem_ready) begin
            backend_count = backend_count + 1;
            backend_launch = mem_ticks;
        end
        if (mem_rsp_valid && mem_rsp_ready) begin
            backend_responses = backend_responses + 1;
            if (card_req || card_ack) $fatal(1, "card response before native rearm");
            if (stores != posted_acks) $fatal(1, "card response before physical commit");
            if (mem_ticks - backend_launch > max_backend_latency)
                max_backend_latency = mem_ticks - backend_launch;
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
    end

    integer host_services = 0, floppy_services = 0, writeback_services = 0;
    integer traffic_phase = 0, traffic_start = 0;
    reg traffic_stopped = 0, host_served = 0;
    initial begin
        wait(por_n_mem);
        traffic_start = mem_ticks + 1;
        forever begin
            @(negedge clk_mem);
            traffic_phase = (mem_ticks - traffic_start) % 128;
            if (stop_competitors && traffic_phase == 127) traffic_stopped = 1;
            if (traffic_stopped) begin
                host_oe = 0; flp_win = 0; flp_guard = 0;
            end else begin
                if (traffic_phase == 0) begin host_oe = 1; host_served = 0; end
                if (host_oe && cpu_done) host_served = 1;
                if (traffic_phase == 24) begin
                    if (!host_served || cpu_dout !== 16'hBEEF)
                        $fatal(1, "fixed host window deadline missed");
                    host_services = host_services + 1;
                    host_oe = 0;
                end
                if (traffic_phase == 60) flp_guard = 1;
                if (traffic_phase == 64) flp_win = 1;
                if (traffic_phase == 88) begin
                    if (!controller.flp_served || floppy_dout !== 16'hCAFE)
                        $fatal(1, "fixed floppy window deadline missed");
                    floppy_services = floppy_services + 1;
                    flp_win = 0; flp_guard = 0;
                end
            end
        end
    end
    reg [15:0] expected_floppy;
    integer next_floppy_tick;
    initial begin
        wait(por_n_sys);
        next_floppy_tick = ticks + 32;
        while (!stop_competitors) begin
            while (ticks < next_floppy_tick) @(negedge clk_sys);
            if (!stop_competitors) begin
                floppy_addr = writeback_services[0] ? 24'h600002 : 24'h600000;
                expected_floppy = writeback_services[0] ? 16'h0DF0 : 16'hD00D;
                floppy_req = 1;
                wait(dut.floppy_crossing.src_state != 0);
                @(negedge clk_sys); floppy_addr = 24'h600100;
                while (!floppy_ack) begin
                    @(negedge clk_sys);
                    if (ticks > next_floppy_tick + 80) $fatal(1, "fixed mailbox request deadline missed");
                end
                repeat (5) begin
                    @(negedge clk_sys);
                    if (!floppy_ack || floppy_data !== expected_floppy)
                        $fatal(1, "floppy mailbox private response changed");
                end
                writeback_services = writeback_services + 1;
                floppy_req = 0;
                wait(!floppy_ack);
            end
            next_floppy_tick = next_floppy_tick + 128;
        end
    end
    always @(posedge clk_sys) begin
        ticks = ticks + 1;
        if (ticks > 2000000) $fatal(1, "platform watchdog");
        if (por_n_sys && fault) $fatal(1, "candidate fault");
        if (`REQ_VALID && `REQ_READY) accepted <= accepted + 1;
        if (`RSP_VALID && `RSP_READY) responses <= responses + 1;
        if (capture_count != last_capture) begin
            if (!capture_valid) $fatal(1, "capture disappeared before observation");
            $fdisplay(traces, "%02x %04x %02x", capture_status, capture_address, capture_data);
            last_capture = capture_count;
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
    always @(posedge `CPU_CLOCK) begin
        ordinary_cycles = ordinary_cycles + 1;
        if (`CORE.runnable && !`CORE.io_space && !`CORE.trap && !ordinary_pending) begin
            ordinary_pending = 1;
            launch_cycle = ordinary_cycles - 1;
            launch_time = $realtime - `CPU_PERIOD;
            pending_address = `CORE.cpu_address;
            pending_write = `CORE.cpu_write;
        end
        if (ordinary_pending && `CORE.cpu_ready) begin
            if (pending_address !== `CORE.cpu_address || pending_write !== `CORE.cpu_write)
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
        integer n, before_count;
        reg [31:0] base;
        reg [15:0] expected_data;
        begin
            repeat (gap_arg) @(negedge clk_sys);
            case (transaction_count % 3)
                0: base = 32'h80000000;
                1: base = 32'h80E00000;
                2: base = 32'h00E00000;
            endcase
            if (word_arg != 0 && offset_arg[0]) $fatal(1, "unaligned word stimulus");
            before_count = accepted;
            pds_address = base + (offset_arg & 32'hFFFFFFFE);
            pds_rw = write_arg == 0;
            pds_fc = transaction_count[0] ? 3'b101 : 3'b001;
            pds_write_data = word_arg != 0 ? value_arg[15:0] :
                             offset_arg[0] ? {8'hD3, value_arg[7:0]} : {value_arg[7:0], 8'hD3};
            pds_as_n = 0;
            #1;
            if (!claim || !dtack_n) $fatal(1, "early claim");
            repeat (2) @(negedge clk_sys);
            if (accepted != before_count) $fatal(1, "request without strobes");
            pds_uds_n = word_arg == 0 != 0 && offset_arg[0];
            pds_lds_n = word_arg == 0 != 0 && !offset_arg[0];
            while (dtack_n) begin
                @(negedge clk_sys);
                if (!claim || error) $fatal(1, "PDS error transaction %0d", transaction_count);
            end
            expected_data = word_arg != 0 ? value_arg[15:0] :
                            offset_arg[0] ? {8'hFF, value_arg[7:0]} : {value_arg[7:0], 8'hFF};
            if (write_arg == 0 && pds_read_data !== expected_data)
                $fatal(1, "PDS read transaction=%0d offset=%h expected=%h actual=%h CPU=%h capture=%h",
                       transaction_count, offset_arg, expected_data, pds_read_data, card_cpu_address, capture_status);
            for (n = 0; n < 3 + transaction_count % 5; n = n + 1) begin
                @(negedge clk_sys);
                if (dtack_n || !claim || accepted != before_count + 1 ||
                    (write_arg == 0 && pds_read_data !== expected_data))
                    $fatal(1, "held AS duplicates or changes transaction");
            end
            pds_as_n = 1;
            pds_uds_n = 1;
            pds_lds_n = 1;
            #1;
            if (claim || !dtack_n) $fatal(1, "AS release");
            @(negedge clk_sys);
            transaction_count = transaction_count + 1;
        end
    endtask

    task unclaimed(input [31:0] a, input [2:0] fc);
        integer before_count;
        begin
            before_count = accepted;
            pds_address = a; pds_fc = fc; pds_as_n = 0;
            pds_uds_n = 0; pds_lds_n = 0; pds_rw = 1;
            repeat (5) begin
                #1;
                if (claim || !dtack_n || error) $fatal(1, "nonclaimed address %h FC %h", a, fc);
                @(negedge clk_sys);
            end
            if (accepted != before_count) $fatal(1, "nonclaimed access reached registers");
            pds_as_n = 1; pds_uds_n = 1; pds_lds_n = 1;
            @(negedge clk_sys);
        end
    endtask

    task unsupported;
        integer before_count;
        begin
            before_count = accepted;
            pds_address = 32'h00E00022; pds_fc = 3'b001;
            pds_as_n = 0; pds_uds_n = 0; pds_lds_n = 1; pds_rw = 1;
            while (!error) @(negedge clk_sys);
            repeat (5) begin
                if (!claim || !dtack_n || accepted != before_count + 1)
                    $fatal(1, "unsupported register bus policy");
                @(negedge clk_sys);
            end
            pds_as_n = 1; pds_uds_n = 1;
            @(negedge clk_sys);
        end
    endtask

    task abort_accepted_read;
        integer before_count;
        begin
            before_count = accepted;
            pds_address = 32'h80000010; pds_fc = 3'b101;
            pds_as_n = 0; pds_uds_n = 0; pds_lds_n = 0; pds_rw = 1;
            while (accepted == before_count) @(negedge clk_sys);
            host_reset = 1;
            repeat (5) begin
                #1;
                if (claim || !dtack_n) $fatal(1, "host reset acknowledged aborted access");
                @(negedge clk_sys);
            end
            pds_as_n = 1; pds_uds_n = 1; pds_lds_n = 1;
            host_reset = 0;
            while (`PDS.state != 3'd1) @(negedge clk_sys);
            if (accepted != before_count + 1 || responses != accepted || `CORE.host_index != 1)
                $fatal(1, "accepted stream read failed to drain across host reset");
            if (mem_rsp_valid) $fatal(1, "aborted backend not drained");
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
        repeat (3) @(negedge clk_mem);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk_mem); por_n_mem = 1;
        repeat (3) @(negedge clk_sys);
        por_n_sys = 1;
        @(negedge clk_sys);
        unclaimed(32'h00D00000, 3'b001);
        unclaimed(32'h80000024, 3'b001);
        unclaimed(32'h80E00025, 3'b001);
        unclaimed(32'h00E00001, 3'b001);
        unclaimed(32'h00E00000, 3'b111);
        unsupported;
        abort_accepted_read;
        while (!$feof(stimulus)) begin
            status = $fscanf(stimulus, "%d %d %d %d %d\n", writing, word_access, offset, value, gap);
            if (status == 5) transact(writing, word_access, offset, value, gap);
            else if (status != -1) $fatal(1, "bad stimulus");
        end
        repeat (600) @(negedge clk_sys);
        if (!boundary || card_cpu_address != 16'h202F) $fatal(1, "wrong boundary %h", card_cpu_address);
        if (capture_valid || capture_count != 39) $fatal(1, "wrong captures %0d", capture_count);
        if (accepted != responses || accepted != transaction_count + 2)
            $fatal(1, "host acceptance/response mismatch");
        stop_competitors = 1;
        wait(traffic_stopped && !host_oe && !flp_win && !flp_guard && !floppy_req);
        wait(dut.ownership.drained && dut.adapter.drained && `CROSS_DRAIN && dut.floppy_crossing.drained && !controller.seq_busy);
        if (mem_rsp_valid || `CORE.cpu_memory_wait) $fatal(1, "backend not drained");
        if (backend_count != backend_responses || stores != posted_acks || stores != early_acks)
            $fatal(1, "native completion/commit counts differ");
        if (stores != 1192 || host_services == 0 || floppy_services == 0 || writeback_services == 0 || refreshes <= 8)
            $fatal(1, "native traffic coverage missing");
        if (writeback_services != writeback_reads) $fatal(1, "floppy request duplicated or lost");
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "memory mismatch byte %h", i);
        end
        if (`CORE.processor.cpu.reg_s !== 8'hFD) $fatal(1, "CPU stack not restored");
        $display("PASS PDS=%0d backend=%0d stores=%0d captures=%0d cpu_cycles=%0d ticks=%0d plus 5 unclaimed, 1 unsupported, 1 reset-drained read",
                 transaction_count, backend_count, stores, capture_count, cpu_completed, ticks);
        $display("mem_ticks=%0d native commits=%0d early_acks=%0d backend_responses=%0d host=%0d floppy_window=%0d writeback=%0d refresh=%0d max_backend_ticks=%0d", mem_ticks, stores, early_acks, backend_responses, host_services, floppy_services, writeback_services, refreshes, max_backend_latency);
        if (ordinary_pending || ordinary_count != 201) $fatal(1, "ordinary latency coverage");
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

