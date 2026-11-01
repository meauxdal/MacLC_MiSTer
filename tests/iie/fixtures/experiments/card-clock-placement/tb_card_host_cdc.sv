`timescale 1ns/1ps
module tb_card_host_cdc;
    reg src_clk = 0, dst_clk = 0;
    always #15.384615 src_clk = !src_clk;
    initial begin
        #1.25;
        forever #7.6923075 dst_clk = !dst_clk;
    end
    reg src_reset = 1, dst_reset = 1;
    reg src_valid = 0, src_rsp_ready = 0;
    reg [23:0] src_request = 0;
    wire src_ready, src_rsp_valid, drained;
    wire [16:0] src_response;
    wire dst_valid, dst_rsp_ready;
    wire [23:0] dst_request;
    reg dst_rsp_valid = 0, busy = 0;
    reg [16:0] dst_response = 0;
    reg [23:0] frozen_request;
    integer destination_cycles = 0, countdown = 0, accepted = 0, returned = 0;
    integer source_accepted = 0, source_returned = 0, i;
    wire dst_ready = !busy && !dst_rsp_valid && destination_cycles % 3 != 0;
    reg [23:0] expected_request;
    reg [16:0] expected_response;
    card_host_cdc dut (.*);

    function [23:0] request_value(input integer n);
        request_value = {n[5:0], n[0], n[1], 16'h1000 ^ n[15:0]};
    endfunction
    function [16:0] response_value(input [23:0] request);
        response_value = {request[0] ^ request[17], request[15:0] ^ 16'hA5C3};
    endfunction
    always @(posedge dst_clk) begin
        destination_cycles = destination_cycles + 1;
        if (destination_cycles > 10000) $fatal(1, "CDC watchdog");
        if (dst_valid && dst_ready) begin
            if (dst_request !== request_value(accepted)) $fatal(1, "request duplicated or torn");
            frozen_request <= dst_request;
            accepted = accepted + 1;
            countdown <= 3 + accepted % 5;
            busy <= 1;
        end
        if (busy) begin
            if (countdown == 0) begin
                busy <= 0;
                dst_rsp_valid <= 1;
                dst_response <= response_value(frozen_request);
            end else countdown <= countdown - 1;
        end
        if (dst_rsp_valid && dst_rsp_ready) begin
            dst_rsp_valid <= 0;
            returned = returned + 1;
        end
    end
    always @(posedge src_clk) begin
        if (src_valid && src_ready) source_accepted = source_accepted + 1;
        if (src_rsp_valid && src_rsp_ready) source_returned = source_returned + 1;
    end
    initial begin
        repeat (3) @(negedge src_clk);
        src_reset = 0; dst_reset = 0;
        for (i = 0; i < 64; i = i + 1) begin
            @(negedge src_clk);
            expected_request = request_value(i);
            expected_response = response_value(expected_request);
            src_request = expected_request;
            src_valid = 1;
            while (!src_ready) @(negedge src_clk);
            @(negedge src_clk);
            src_valid = 0;
            src_request = ~expected_request;
            while (!src_rsp_valid) @(negedge src_clk);
            repeat (1 + i % 7) begin
                if (src_response !== expected_response || !src_rsp_valid || src_ready)
                    $fatal(1, "coherent response/error bit changed under backpressure");
                @(negedge src_clk);
            end
            src_rsp_ready = 1;
            @(negedge src_clk); src_rsp_ready = 0;
        end
        repeat (5) @(negedge src_clk);
        if (!drained || accepted != 64 || returned != 64 || source_accepted != 64 || source_returned != 64)
            $fatal(1, "CDC exact-once counts");
        $display("PASS 64 exact-once normalized requests and coherent 17-bit responses under backpressure");
        $finish;
    end
endmodule
