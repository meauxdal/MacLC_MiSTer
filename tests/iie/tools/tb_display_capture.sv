`timescale 1ns/1ps
module tb_display_capture;
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
    integer ticks = 0, stores = 0;
    always @(posedge clk) begin
        ticks <= ticks + 1;
        if (ticks > 4000000 || fault || boundary) $fatal(1, "display capture fault/watchdog");
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (memory_pending) begin
            if (memory_wait == 0) begin
                mem_rsp_valid <= 1;
                memory_pending <= 0;
            end else memory_wait <= memory_wait - 1;
        end
        if (mem_valid && !mem_rsp_valid && !memory_pending) begin
            if (mem_write) begin
                memory[mem_addr] <= mem_wdata;
                stores <= stores + 1;
            end
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
    string image, cases_image;
    integer count, index, physical, saved_stores;
    reg [47:0] cases [0:1023];
    reg [15:0] target;
    reg [7:0] mask, status, value, before_byte, other_byte;
    reg aux, report;
    initial begin
        if (!$value$plusargs("image=%s", image) ||
            !$value$plusargs("cases=%s", cases_image) ||
            !$value$plusargs("count=%d", count)) $fatal(1, "missing test input");
        if (!$value$plusargs("latency=%d", memory_latency)) memory_latency = 0;
        $readmemh(image, memory);
        $readmemh(cases_image, cases, 0, count - 1);
        if ($test$plusargs("hires-control")) force dut.runtime_hires = 0;
        repeat (4) @(negedge clk); por_n = 1;
        host(0, 33, 16'h20);
        host(0, 32, 16'h80);
        wait(capture_valid);
        if (capture_status != 8'h80 || capture_address != 16'hFFFC)
            $fatal(1, "reset capture mismatch");
        host(0, 32, 16'h88); host(0, 12, 0);
        for (index = 0; index < count; index = index + 1) begin
            {target, mask, status, value, aux, report} = cases[index][41:0];
            wait(capture_valid);
            if (capture_address != 16'hC07D || dut.capture_data != mask)
                $fatal(1, "setup capture mismatch case=%0d", index);
            physical = {aux, target};
            before_byte = memory[physical >> 1][8*physical[0] +: 8];
            other_byte = memory[(physical ^ 17'h10000) >> 1][8*physical[0] +: 8];
            saved_stores = stores;
            host(0, 33, {8'b0, mask});
            host(0, 32, report ? 16'h98 : 16'h88);
            host(0, 12, 0);
            wait(capture_valid);
            if (status != 0) begin
                if (capture_address != target || capture_status != status || dut.capture_data != value)
                    $fatal(1, "display mismatch case=%0d address=%h status=%h expected=%h data=%h",
                        index, capture_address, capture_status, status, dut.capture_data);
                repeat (80) @(negedge clk);
                if (memory[physical >> 1][8*physical[0] +: 8] !== before_byte || stores != saved_stores)
                    $fatal(1, "store committed before release case=%0d", index);
                if (report) begin
                    req_write = 0;
                    host(1, 4, 0);
                    if (rsp_rdata != target) $fatal(1, "address release data mismatch");
                    req_write = 1;
                end else host(0, 12, 0);
                wait(capture_valid);
            end
            if (capture_address != 16'hC07D || dut.capture_data != 8'hEE)
                $fatal(1, "unexpected trap after store case=%0d address=%h status=%h", index, capture_address, capture_status);
            if (memory[physical >> 1][8*physical[0] +: 8] !== value || stores != saved_stores + 1 ||
                memory[(physical ^ 17'h10000) >> 1][8*physical[0] +: 8] !== other_byte)
                $fatal(1, "store/bank/commit mismatch case=%0d", index);
            host(0, 12, 0);
        end
        host(1, 32, 16'h0802);
        wait(!dut.reset_pending && !dut.cpu_running);
        $display("PASS %0d CPU display cases: masks, both banks/pages, HiRes boundaries, held writes, ACK/address release, exact-once commits", count);
        $finish;
    end
endmodule
