`timescale 1ns/1ps
module tb_card_memory_cdc;
    parameter ADDR_WIDTH = 17;
    integer src_half = 5, dst_half = 7, dst_phase = 3;
    reg src_clk = 0, dst_clk = 0;
    initial begin
        if ($value$plusargs("src_half=%d", src_half)) begin end
        forever #(src_half) src_clk = !src_clk;
    end
    initial begin
        if ($value$plusargs("dst_half=%d", dst_half)) begin end
        if ($value$plusargs("phase=%d", dst_phase)) begin end
        #(dst_phase);
        forever #(dst_half) dst_clk = !dst_clk;
    end
    reg src_reset = 1, dst_reset = 1;
    reg src_valid = 0, src_write = 0, src_rsp_ready = 0;
    reg [ADDR_WIDTH-1:0] src_addr = 0;
    reg [15:0] src_wdata = 0;
    wire src_ready, src_rsp_valid, drained;
    wire [15:0] src_rdata;
    wire dst_valid, dst_write, dst_rsp_ready;
    wire [ADDR_WIDTH-1:0] dst_addr;
    wire [15:0] dst_wdata;
    reg dst_rsp_valid = 0;
    reg [15:0] dst_rdata = 0;
    reg busy = 0;
    integer dst_cycle = 0, remaining = 0;
    wire dst_ready = !dst_reset && !busy && dst_cycle % 4 != 0;
    reg pending_write;
    reg [ADDR_WIDTH-1:0] pending_addr;
    reg [15:0] pending_data;
    reg [15:0] memory [0:255];
    reg [15:0] expected_memory [0:255];
    reg [ADDR_WIDTH-1:0] expected_addr [0:299];
    reg expected_write [0:299];
    reg [15:0] expected_data [0:299];
    integer src_requests = 0, dst_requests = 0, dst_responses = 0, src_responses = 0;
    integer request_stalls = 0, response_stalls = 0;
    integer n, i, delay_cycles;
    reg [15:0] wanted, saved_response;
    reg [ADDR_WIDTH-1:0] address_value;
    reg stalled_dst = 0, stalled_src = 0;
    reg [ADDR_WIDTH-1:0] held_addr;
    reg held_write;
    reg [15:0] held_wdata, held_rdata;
    card_memory_cdc #(.ADDR_WIDTH(ADDR_WIDTH)) dut (.*);

    always @(posedge src_clk) begin
        if (!src_reset) begin
            if (src_valid && src_ready) src_requests <= src_requests + 1;
            if (src_rsp_valid && src_rsp_ready) src_responses <= src_responses + 1;
            if (src_rsp_valid && !src_rsp_ready) response_stalls <= response_stalls + 1;
            if (stalled_src && (!src_rsp_valid || src_rdata !== held_rdata))
                $fatal(1, "source response changed under backpressure");
            stalled_src <= src_rsp_valid && !src_rsp_ready;
            if (src_rsp_valid) held_rdata <= src_rdata;
            if (!drained && src_ready) $fatal(1, "mailbox reused before response consumption");
        end else stalled_src <= 0;
    end

    always @(posedge dst_clk) begin
        if (dst_reset) begin
            busy <= 0;
            dst_rsp_valid <= 0;
            dst_cycle <= 0;
            stalled_dst <= 0;
        end else begin
            dst_cycle <= dst_cycle + 1;
            if (dst_valid && !dst_ready) request_stalls <= request_stalls + 1;
            if (stalled_dst && (!dst_valid || dst_addr !== held_addr ||
                                dst_write !== held_write || dst_wdata !== held_wdata))
                $fatal(1, "destination request changed under backpressure");
            stalled_dst <= dst_valid && !dst_ready;
            if (dst_valid) begin
                held_addr <= dst_addr;
                held_write <= dst_write;
                held_wdata <= dst_wdata;
            end
            if (dst_valid && dst_ready) begin
                if (dst_requests >= src_requests || dst_addr !== expected_addr[dst_requests] ||
                    dst_write !== expected_write[dst_requests] || dst_wdata !== expected_data[dst_requests])
                    $fatal(1, "mailbox payload/order mismatch at %0d", dst_requests);
                pending_addr <= dst_addr;
                pending_write <= dst_write;
                pending_data <= dst_wdata;
                remaining <= dst_requests % 7 + 1;
                busy <= 1;
                dst_requests <= dst_requests + 1;
            end
            if (busy && !dst_rsp_valid) begin
                if (remaining != 0) remaining <= remaining - 1;
                else begin
                    if (pending_write) memory[pending_addr[7:0]] <= pending_data;
                    dst_rdata <= pending_write ? pending_data : memory[pending_addr[7:0]];
                    dst_rsp_valid <= 1;
                end
            end
            if (dst_rsp_valid && dst_rsp_ready) begin
                dst_rsp_valid <= 0;
                busy <= 0;
                dst_responses <= dst_responses + 1;
            end
        end
    end
    task src_tick;
        begin @(posedge src_clk); #1; end
    endtask
    task cold_reset;
        begin
            if (src_requests != 0 && (!drained || src_rsp_valid || busy || dst_valid))
                $fatal(1, "reset outside documented quiescent condition");
            src_reset = 1;
            dst_reset = 1;
            repeat (5) src_tick;
            repeat (5) begin @(posedge dst_clk); #1; end
            src_reset = 0;
            dst_reset = 0;
            repeat (4) src_tick;
            if (!drained || !src_ready || src_rsp_valid || dst_valid || dst_rsp_ready)
                $fatal(1, "cold reset did not clear mailbox");
        end
    endtask
    initial begin
        for (i = 0; i < 256; i = i + 1) begin
            memory[i] = 16'h5AA5 ^ (i * 16'h0101);
            expected_memory[i] = memory[i];
        end
        cold_reset;
        for (n = 0; n < 257; n = n + 1) begin
            // Consecutive write/read pairs exercise all address bits and byte order.
            address_value = ADDR_WIDTH'((n / 2) * 7919) ^ (ADDR_WIDTH'(1) << (ADDR_WIDTH-1));
            expected_addr[n] = address_value;
            expected_write[n] = !(n % 2);
            expected_data[n] = 16'hA63D ^ (16'(n) * 16'h0029);
            wanted = expected_write[n] ? expected_data[n] : expected_memory[address_value[7:0]];
            src_write = expected_write[n];
            src_addr = address_value;
            src_wdata = expected_data[n];
            src_valid = 1;
            if (!src_ready) $fatal(1, "source not ready at transaction start");
            src_tick;
            src_valid = 0;
            // Change current inputs immediately; only the accepted mailbox may cross.
            src_write = !src_write;
            src_addr = ~src_addr;
            src_wdata = ~src_wdata;
            if (drained || src_ready) $fatal(1, "source not busy after acceptance");
            while (!src_rsp_valid) src_tick;
            if (src_rdata !== wanted) $fatal(1, "reply byte/order mismatch %0d: %h != %h", n, src_rdata, wanted);
            saved_response = src_rdata;
            delay_cycles = n % 6 + 1;
            repeat (delay_cycles) begin
                src_valid = 1;
                src_tick;
                if (src_ready || drained || !src_rsp_valid || src_rdata !== saved_response)
                    $fatal(1, "response consumption did not block reuse");
            end
            src_valid = 0;
            src_rsp_ready = 1;
            src_tick;
            src_rsp_ready = 0;
            if (!drained || !src_ready || src_rsp_valid) $fatal(1, "source response retirement");
            if (expected_write[n]) expected_memory[address_value[7:0]] = expected_data[n];
            if (n == 126) cold_reset;
        end
        repeat (5) src_tick;
        if (src_requests != 257 || dst_requests != 257 || dst_responses != 257 || src_responses != 257)
            $fatal(1, "counts src %0d/%0d dst %0d/%0d", src_requests, src_responses, dst_requests, dst_responses);
        if (request_stalls == 0 || response_stalls == 0) $fatal(1, "missing backpressure coverage");
        for (i = 0; i < 256; i = i + 1)
            if (memory[i] !== expected_memory[i]) $fatal(1, "final memory mismatch");
        $display("PASS CDC width=%0d clocks=%0d/%0d phase=%0d requests=257 responses=257", ADDR_WIDTH, src_half, dst_half, dst_phase);
        $finish;
    end
    initial begin #1000000; $fatal(1, "test timeout"); end
endmodule
