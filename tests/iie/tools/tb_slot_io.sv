`timescale 1ns/1ps
module tb_slot_io;
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
        if (ticks > 1000000 || fault || boundary) $fatal(1, "slot IO fault/watchdog cause=%0d", dut.first_fault);
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
    string image;
    integer slot, offset, index = 0;
    reg [15:0] target;
    reg [7:0] outgoing, incoming;
    bit wrong_release;
    task peek(input bit word_access, input [5:0] offset, input [15:0] expected);
        begin
            req_write = 0;
            host(word_access, offset, 0);
            if (rsp_rdata !== expected) $fatal(1, "host read offset=%h got=%h expected=%h", offset, rsp_rdata, expected);
            req_write = 1;
        end
    endtask
    initial begin
        if (!$value$plusargs("image=%s", image)) $fatal(1, "missing image");
        if (!$value$plusargs("latency=%d", memory_latency)) memory_latency = 0;
        wrong_release = $test$plusargs("release-control");
        $readmemh(image, memory);
        if ($test$plusargs("reply-control")) force dut.host_return = 0;
        repeat (4) @(negedge clk); por_n = 1;
        host(0, 33, 16'h20); host(0, 32, 16'h80);
        wait(capture_valid);
        if (capture_status != 8'h80 || capture_address != 16'hFFFC)
            $fatal(1, "reset capture mismatch");
        host(0, 32, 16'h88); host(0, 12, 0);
        for (slot = 1; slot <= 7; slot = slot + 1) begin
            if (slot != 6) begin
                for (offset = 0; offset < 16; offset = offset + 1) begin
                    target = 16'hC080 + 16'(slot * 16 + offset);
                    outgoing = 8'(index * 37 + 83);
                    incoming = 8'(index * 53 + 97);
                    wait(capture_valid);
                    if (capture_address != target || capture_status != 8'h08 || dut.capture_data != outgoing)
                        $fatal(1, "slot write capture mismatch index=%0d", index);
                    peek(0, 1, 8); peek(1, 4, target); peek(0, 12, {8'b0, outgoing});
                    repeat (80) @(negedge clk);
                    if (!capture_valid || capture_address != target) $fatal(1, "slot write escaped capture");
                    host(0, 12, 0);
                    wait(capture_valid);
                    if (capture_address != target || capture_status != 8'h09)
                        $fatal(1, "slot read capture mismatch index=%0d", index);
                    peek(0, 1, 9); peek(1, 4, target); peek(0, 25, 0);
                    repeat (80) @(negedge clk);
                    if (!capture_valid || capture_address != target) $fatal(1, "slot read escaped capture");
                    if (wrong_release) begin
                        host(0, 12, 0);
                        repeat (4) @(negedge clk);
                        $fatal(1, "wrong release accepted");
                    end
                    else host(0, 25, {8'b0, incoming});
                    wait(capture_valid);
                    if (capture_address != 16'hC07D || capture_status != 8'hE0 ||
                        dut.capture_data != incoming || memory[17'h100][7:0] != incoming)
                        $fatal(1, "slot reply mismatch index=%0d got=%h expected=%h", index, dut.capture_data, incoming);
                    host(0, 12, 0);
                    index = index + 1;
                end
            end
        end
        host(1, 32, 16'h0802);
        wait(!dut.reset_pending && !dut.cpu_running);
        $display("PASS %0d software-slot registers: CPU writes/reads, PDS status/address/data, held capture, read reply, CPU commit", index);
        $finish;
    end
endmodule
