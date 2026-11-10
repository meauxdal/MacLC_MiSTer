`timescale 1ns/1ps
module tb_runtime;
    reg clk = 0, por_n = 0;
    always #15.3845 clk = !clk;
    reg req_valid = 0, req_word = 0, req_write = 1;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error, fault, boundary;
    wire [15:0] rsp_rdata, cpu_address;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    reg mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    reg [15:0] memory [0:131071];
    wire capture_valid;
    wire [7:0] capture_status;
    wire [15:0] capture_address;
    card_irq_candidate dut (
        .clk(clk), .por_n(por_n), .runtime_mode(1'b1),
        .req_valid(req_valid), .req_ready(req_ready), .req_offset(req_offset),
        .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_valid(mem_valid), .mem_ready(!mem_rsp_valid), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata), .fault(fault), .boundary(boundary),
        .cpu_address(cpu_address), .instruction_address(), .capture_valid(capture_valid),
        .capture_status(capture_status), .capture_address(capture_address),
        .capture_data(), .capture_count(), .cpu_completed()
    );
    integer ticks = 0;
    reg expect_fault = 0;
    always @(posedge clk) begin
        ticks <= ticks + 1;
        if (ticks > 100000 || (fault && !expect_fault) || boundary) $fatal(1, "runtime smoke fault/watchdog");
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (mem_valid && !mem_rsp_valid) begin
            if (mem_write) memory[mem_addr] <= mem_wdata;
            mem_rdata <= memory[mem_addr];
            mem_rsp_valid <= 1;
        end
    end
    task host(input bit word_access, input [5:0] offset, input [15:0] value);
        begin
            @(negedge clk);
            req_word = word_access; req_offset = offset; req_wdata = value; req_valid = 1;
            do @(posedge clk); while (!req_ready);
            @(negedge clk); req_valid = 0;
            wait(rsp_valid);
            if (rsp_error) $fatal(1, "host transaction failed offset=%h", offset);
            @(negedge clk);
        end
    endtask
    task byte_at(input integer address, input [7:0] value);
        if (address[0]) memory[address / 2][15:8] = value;
        else memory[address / 2][7:0] = value;
    endtask
    reg [7:0] program_bytes [0:23];
    initial begin
        for (integer i = 0; i < 131072; i = i + 1) memory[i] = 0;
        // Synthetic monitor: write text, read key, clear strobe, read key again.
        {program_bytes[0], program_bytes[1], program_bytes[2], program_bytes[3],
         program_bytes[4], program_bytes[5], program_bytes[6], program_bytes[7],
         program_bytes[8], program_bytes[9], program_bytes[10], program_bytes[11],
         program_bytes[12], program_bytes[13], program_bytes[14], program_bytes[15],
         program_bytes[16], program_bytes[17], program_bytes[18], program_bytes[19],
         program_bytes[20], program_bytes[21], program_bytes[22], program_bytes[23]} =
            192'hA9A58D0004AD00C08D0002AD10C0AD00C08D01024C77FAEA;
        for (integer i = 0; i < 24; i = i + 1) byte_at('h23A62 + i, program_bytes[i]);
        byte_at('h27FFC, 8'h62); byte_at('h27FFD, 8'hFA);
        repeat (4) @(negedge clk); por_n = 1;
        host(1, 32, 16'h0802);
        host(0, 33, 16'h20);
        host(0, 32, 16'h80);
        wait(capture_valid);
        if (capture_status != 8'h80 || capture_address != 16'hFFFC)
            $fatal(1, "reset capture mismatch");
        host(0, 32, 16'h88); host(0, 12, 0);
        wait(capture_valid);
        if (capture_status != 8'h42 || capture_address != 16'h0400)
            $fatal(1, "runtime display capture mismatch");
        host(0, 24, 16'h41);
        host(0, 12, 0);
        wait(memory['h201 / 2] == 16'h41C1);
        if (memory['h400 / 2][7:0] != 8'hA5 || dut.keyboard[7])
            $fatal(1, "runtime text or keyboard mismatch");
        // Command/Option ride in run command bits 0-1 as the Apple keys.
        host(0, 32, 16'h89);
        if (dut.apple_keys != 2'b01) $fatal(1, "Open-Apple not latched from $89");
        host(0, 32, 16'h8A);
        if (dut.apple_keys != 2'b10) $fatal(1, "Solid-Apple not latched from $8A");
        host(0, 32, 16'h88);
        if (dut.apple_keys != 2'b00) $fatal(1, "$88 did not clear the Apple keys");
        // Pause carries the same flag bits: $90 (motor bit 4) and $91.
        host(0, 32, 16'h90);
        if (!dut.runtime_paused) $fatal(1, "$90 did not pause");
        host(0, 12, 0);
        host(0, 32, 16'h91);
        if (!dut.runtime_paused || dut.apple_keys != 2'b01) $fatal(1, "$91 pause/key mismatch");
        host(0, 12, 0);
        host(0, 32, 16'h88);
        if (dut.runtime_paused || dut.apple_keys != 2'b00) $fatal(1, "$88 did not resume");
        // An unknown command still faults, and a host restart recovers.
        expect_fault = 1;
        host(0, 32, 16'h8C);
        repeat (2) @(negedge clk);
        if (!fault || dut.first_fault != 6) $fatal(1, "unknown command did not fault");
        host(1, 32, 16'h0802);
        host(0, 33, 16'h20);
        host(0, 32, 16'h80);
        wait(capture_valid);
        if (fault || capture_status != 8'h80 || capture_address != 16'hFFFC)
            $fatal(1, "restart after fault did not recover");
        expect_fault = 0;
        $display("PASS runtime vector mapping, text capture/commit, keyboard strobe and clear, Apple keys, flagged pause, fault recovery");
        $finish;
    end
endmodule
