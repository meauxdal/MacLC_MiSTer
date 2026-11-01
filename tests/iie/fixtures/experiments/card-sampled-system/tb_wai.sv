`timescale 1ns/1ps
module tb_wai #(parameter FAST = 0, MASKED = 0);
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0;
    reg req_valid = 0, req_word = 0, req_write = 1, rsp_ready = 0;
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
    wire mem_ready = !busy && !mem_rsp_valid;
    reg mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    card_irq_candidate #(.PACE_FAST(FAST)) dut (.*);
    reg [15:0] memory [0:131071];
    reg busy = 0, pending_write;
    reg [16:0] pending_address;
    reg [15:0] pending_data;
    integer delay_left = 0, clocks = 0, operations = 0, replies = 0;
    integer vectors = 0, rtis = 0, i, saved_operations, saved_completed, samples;

    always @(posedge clk) begin
        clocks = clocks + 1;
        if (clocks > 30000) $fatal(1, "WAI timeout PC=%h", cpu_address);
        if (por_n && fault) $fatal(1, "WAI card fault PC=%h", cpu_address);
        if (mem_valid && mem_ready) begin
            busy <= 1;
            pending_write <= mem_write;
            pending_address <= mem_addr;
            pending_data <= mem_wdata;
            delay_left <= 80;
            operations = operations + 1;
        end
        if (busy) begin
            if (delay_left == 0) begin
                if (pending_write) memory[pending_address] <= pending_data;
                mem_rdata <= memory[pending_address];
                mem_rsp_valid <= 1;
                busy <= 0;
            end else delay_left <= delay_left - 1;
        end
        if (mem_rsp_valid && mem_rsp_ready) begin
            mem_rsp_valid <= 0;
            replies = replies + 1;
        end
        if (dut.cpu_ready && dut.vector_pull && cpu_address == 16'hFFFE) vectors = vectors + 1;
        if (dut.cpu_ready && dut.rti_done) rtis = rtis + 1;
        if (dut.processor.waiting && (dut.cpu_valid || dut.cpu_ready || dut.master_valid[1]))
            $fatal(1, "WAI issued a transaction");
    end

    task put(input integer address, input [7:0] value);
        if (address % 2) memory[address / 2][15:8] = value;
        else memory[address / 2][7:0] = value;
    endtask

    task host_write(input [5:0] offset, input [7:0] value);
        begin
            @(negedge clk);
            req_offset = offset;
            req_wdata = {8'b0, value};
            req_valid = 1;
            @(posedge clk);
            while (!req_ready) @(posedge clk);
            @(negedge clk); req_valid = 0;
            while (!rsp_valid) @(negedge clk);
            if (rsp_error) $fatal(1, "WAI host error");
            rsp_ready = 1;
            @(negedge clk); rsp_ready = 0;
        end
    endtask

    initial begin
        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        put('h23FFC, 'h00); put('h23FFD, 'h20);
        put('h23FFE, 'h00); put('h23FFF, 'h22);
        put('h2000, MASKED ? 8'h78 : 8'h58); // SEI/CLI; WAI; LDA #42; STA 0200; JMP 2043.
        put('h2001, 'hCB); put('h2002, 'hA9); put('h2003, 'h42);
        put('h2004, 'h8D); put('h2005, 'h00); put('h2006, 'h02);
        put('h2007, 'h4C); put('h2008, 'h43); put('h2009, 'h20);
        put('h2200, 'hEE); put('h2201, 'h01); put('h2202, 'h02); put('h2203, 'h40);
        repeat (3) @(negedge clk);
        por_n = 1;
        host_write('h21, 'hFC);
        host_write('h20, 'h80);
        wait(capture_valid);
        if (capture_status != 'h80 || capture_address != 'hFFFC) $fatal(1, "WAI reset capture");
        host_write('h20, 'h88);
        host_write('h0C, 0);
        wait(dut.processor.waiting);
        @(negedge clk);
        saved_operations = operations;
        saved_completed = cpu_completed;
        samples = 0;
        while (samples < 8) begin
            @(negedge clk);
            if (dut.pace_due) samples = samples + 1;
            if (!dut.processor.waiting || operations != saved_operations || cpu_completed != saved_completed)
                $fatal(1, "WAI did not hold idle");
        end
        host_write('h20, 'hA8);
        wait(!dut.processor.waiting);
        if (!MASKED) wait(vectors == 1);
        host_write('h20, 'h88);
        wait(boundary);
        wait(dut.drained && !busy && !mem_rsp_valid);
        @(negedge clk);
        if (operations != replies || vectors != (MASKED ? 0 : 1) || rtis != vectors ||
            memory['h100] !== (MASKED ? 16'h0042 : 16'h0142) || capture_count != 1 ||
            dut.processor.cpu.reg_s !== 8'hFD)
            $fatal(1, "WAI result/accounting mismatch");
        $display("PASS WAI fast=%0d masked=%0d vectors=%0d RTI=%0d operations=%0d completions=%0d",
                 FAST, MASKED, vectors, rtis, operations, cpu_completed);
        $finish;
    end
endmodule
