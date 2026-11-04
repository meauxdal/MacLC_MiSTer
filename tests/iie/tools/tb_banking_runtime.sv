`timescale 1ns/1ps
module tb_banking_runtime;
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
    reg memory_pending = 0;
    integer memory_latency = 0, memory_wait = 0;
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
        .mem_valid(mem_valid), .mem_ready(!mem_rsp_valid && !memory_pending), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata), .fault(fault), .boundary(boundary),
        .cpu_address(cpu_address), .instruction_address(), .capture_valid(capture_valid),
        .capture_status(capture_status), .capture_address(capture_address),
        .capture_data(), .capture_count(), .cpu_completed()
    );
    integer ticks = 0;
    always @(posedge clk) begin
        ticks <= ticks + 1;
        if (ticks > 100000 || fault || boundary) $fatal(1, "banking runtime fault/watchdog");
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (memory_pending) begin
            if (memory_wait == 0) begin
                mem_rsp_valid <= 1;
                memory_pending <= 0;
            end else memory_wait <= memory_wait - 1;
        end
        if (mem_valid && !mem_rsp_valid && !memory_pending) begin
            if (mem_write) memory[mem_addr] <= mem_wdata;
            mem_rdata <= memory[mem_addr];
            memory_pending <= 1;
            memory_wait <= memory_latency;
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
    string image, expected_image;
    integer count, index;
    reg [7:0] expected [0:255];
    wire old_firmware_test = dut.cpu_address == 16'hE000 && !dut.high_read;
    initial begin
        if (!$value$plusargs("image=%s", image) ||
            !$value$plusargs("expected=%s", expected_image) ||
            !$value$plusargs("count=%d", count)) $fatal(1, "missing test input");
        $readmemh(image, memory);
        $readmemh(expected_image, expected, 0, count - 1);
        if (!$value$plusargs("latency=%d", memory_latency)) memory_latency = 0;
        if ($test$plusargs("status-control")) force dut.banking_status = 0;
        if ($test$plusargs("rom-control"))
            force dut.firmware_test = old_firmware_test;
        repeat (4) @(negedge clk); por_n = 1;
        host(0, 33, 16'h20);
        host(0, 32, 16'h80);
        wait(capture_valid);
        if (capture_status != 8'h80 || capture_address != 16'hFFFC)
            $fatal(1, "reset capture mismatch");
        host(0, 32, 16'h88); host(0, 12, 0);
        for (index = 0; index < count; index = index + 1) begin
            wait(capture_valid);
            if (capture_status != 8'hE0 || capture_address != 16'hC07D ||
                dut.capture_data !== expected[index])
                $fatal(1, "bank result %0d pc=%h got=%h expected=%h capture=%h/%h",
                    index, dut.instruction_address, dut.capture_data, expected[index],
                    capture_address, capture_status);
            repeat (7) @(negedge clk);
            if (dut.capture_data !== expected[index]) $fatal(1, "held report changed");
            host(0, 12, 0);
        end
        host(1, 32, 16'h0802);
        wait(!dut.reset_pending && !dut.cpu_running);
        repeat (4) @(negedge clk);
        if ({dut.processor.banks.ramrd, dut.processor.banks.ramwrt,
             dut.processor.banks.altzp, dut.processor.banks.lc_read,
             dut.processor.banks.lc_bank1, dut.processor.banks.lc_prewrite} !== 6'b0 ||
            !dut.processor.banks.lc_write) $fatal(1, "reset retained banking");
        $display("PASS actual CPU banking status, switch writes, protected stores and main/aux language RAM: %0d reports", count);
        $finish;
    end
endmodule
