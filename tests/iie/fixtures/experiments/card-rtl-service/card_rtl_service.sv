`timescale 1ns/1ps
module card_rtl_service;
    reg clk_sys = 0, clk_mem = 0;
    integer sys_half = 7, sys_phase = 1;
    always #5 clk_mem = !clk_mem;
    initial begin
        if (!$value$plusargs("sys_half=%d", sys_half)) sys_half = 7;
        if (!$value$plusargs("sys_phase=%d", sys_phase)) sys_phase = 1;
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
    card_platform dut (.*);
    reg [15:0] memory [0:131071];
    integer ticks = 0, mem_ticks = 0, backend_count = 0, backend_responses = 0, stores = 0;
    integer backend_launch = 0, max_backend_latency = 0;
    integer posted_acks = 0, early_acks = 0, last_capture = 0;
    integer scanned, sequence_number, writing, width, offset, value, reply_value;
    integer last_sequence = 0;
    reg [1023:0] image_path, dump_path;
    reg [2:0] phase = 0;
    always @(posedge clk_mem) phase <= phase + 3'd1;
    wire clk8 = phase >= 4;
    reg init = 1;
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
    sdram controller (
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_dout),
        .sd_addr(sd_addr), .sd_dqm(sd_dqm), .sd_ba(sd_ba),
        .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(init), .clk_64(clk_mem), .clk_8(clk8), .din(16'b0), .dout(floppy_dout),
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
                if (!controller.src_eth || dut.ownership.owner || sd_dqm != 0)
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
        if (por_n_mem && fault) begin $display("ERROR candidate_fault %04x", card_cpu_address); $fflush(); $finish; end
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


    always @(posedge clk_sys) begin
        ticks = ticks + 1;
        if (ticks > 2000000) begin
            $display("ERROR watchdog"); $fflush(); $finish;
        end
        if (capture_count != last_capture) begin
            if (!capture_valid) begin
                $display("ERROR vanished_capture"); $fflush(); $finish;
            end
            $display("CAP %02x %04x %0d %02x", capture_status, capture_address,
                     dut.card.card.capture_write, capture_data);
            $fflush();
            last_capture = capture_count;
        end
    end

    task transact(input integer seq, input integer write_arg, input integer bits,
                  input integer off, input integer data_arg, output integer result);
        integer wait_cycles;
        reg [31:0] base;
        begin
            case (seq % 3)
                0: base = 32'h80000000;
                1: base = 32'h80E00000;
                default: base = 32'h00E00000;
            endcase
            @(negedge clk_sys);
            pds_address = base + (off & 32'hFFFFFFFE);
            pds_rw = write_arg == 0;
            pds_fc = 3'b101;
            pds_write_data = bits == 16 ? data_arg[15:0] :
                             off[0] ? {8'hFF, data_arg[7:0]} : {data_arg[7:0], 8'hFF};
            pds_as_n = 0;
            pds_uds_n = bits == 8 && off[0];
            pds_lds_n = bits == 8 && !off[0];
            wait_cycles = 0;
            while (dtack_n) begin
                @(negedge clk_sys);
                wait_cycles = wait_cycles + 1;
                if (error || fault || wait_cycles > 10000) begin
                    $display("ERROR transaction %0d %0d", seq, off); $fflush(); $finish;
                end
            end
            result = write_arg != 0 ? data_arg : bits == 16 ? {16'b0, pds_read_data} :
                     off[0] ? {24'b0, pds_read_data[7:0]} : {24'b0, pds_read_data[15:8]};
            repeat (3) @(negedge clk_sys);
            pds_as_n = 1; pds_uds_n = 1; pds_lds_n = 1;
            @(negedge clk_sys);
        end
    endtask

    initial begin
        if (!$value$plusargs("image=%s", image_path) || !$value$plusargs("dump=%s", dump_path)) begin
            $display("ERROR missing_image_or_dump"); $fflush(); $finish;
        end
        $readmemh(image_path, memory);
        repeat (3) @(negedge clk_mem);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk_mem); por_n_mem = 1;
        repeat (3) @(negedge clk_sys); por_n_sys = 1;
        transact(0, 1, 16, 28, 16384, reply_value);
        transact(0, 1, 8, 13, 0, reply_value);
        transact(0, 1, 8, 33, 252, reply_value);
        transact(0, 1, 8, 32, 128, reply_value);
        $display("READY"); $fflush();
        forever begin
            // Blocking input intentionally pauses all simulated clocks.
            scanned = $fscanf(32'h80000000, "%d %d %d %d %d",
                              sequence_number, writing, width, offset, value);
            if (scanned == -1) $finish;
            if (scanned != 5 || sequence_number != last_sequence + 1 ||
                (writing != 0 && writing != 1) || (width != 8 && width != 16) ||
                offset < 0 || offset > 35 || (width == 16 && offset[0]) ||
                value < 0 || (width == 8 && value > 255) || value > 65535) begin
                $display("ERROR invalid_request"); $fflush(); $finish;
            end
            repeat (600) @(negedge clk_sys);
            if (writing == 0 && width == 8 && offset == 1 && boundary) begin
                wait(dut.card_crossing.drained && dut.adapter.drained && dut.ownership.drained);
                $writememh(dump_path, memory);
                $display("STOP %0d %04x", sequence_number, card_cpu_address); $fflush(); $finish;
            end
            transact(sequence_number, writing, width, offset, value, reply_value);
            last_sequence = sequence_number;
            $display("REPLY %0d %0d", sequence_number, reply_value); $fflush();
        end
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

