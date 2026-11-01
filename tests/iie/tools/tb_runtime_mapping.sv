`timescale 1ns/1ps
module tb_runtime_mapping;
    reg clk = 0, por_n = 0, runtime_mode = 0;
    always #5 clk = !clk;
    reg req_valid = 0, req_word = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error;
    wire [3:0] debug_state;
    card_irq_candidate dut (
        .clk(clk), .por_n(por_n), .runtime_mode(runtime_mode),
        .req_valid(req_valid), .req_ready(req_ready), .req_offset(req_offset),
        .req_word(req_word), .req_write(1'b1), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1), .rsp_error(rsp_error),
        .mem_ready(1'b0), .mem_rsp_valid(1'b0), .mem_rdata(16'b0),
        .debug_state(debug_state)
    );
    task write_reg(input [5:0] offset, input word_access, input [15:0] value);
        begin
            @(negedge clk);
            req_offset = offset;
            req_word = word_access;
            req_wdata = value;
            req_valid = 1;
            do @(posedge clk); while (!req_ready);
            @(negedge clk); req_valid = 0;
            do @(posedge clk); while (!rsp_valid);
            if (rsp_error) $fatal(1, "register write failed");
        end
    endtask
    task check_mapping(input expected);
        begin
            repeat (8) @(posedge clk);
            if (debug_state[3] !== expected) $fatal(1, "mapping mismatch");
        end
    endtask
    initial begin
        force dut.cpu_valid = 0;
        repeat (4) @(posedge clk);
        @(negedge clk); por_n = 1;
        write_reg(6'h21, 0, 16'h00FC);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(0);
        write_reg(6'h20, 1, 16'h0802);
        check_mapping(0);
        write_reg(6'h21, 0, 16'h0023);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(1);
        write_reg(6'h20, 1, 16'h0802);
        check_mapping(1);
        write_reg(6'h21, 0, 16'h00FC);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(0);
        runtime_mode = 1;
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(1);
        $display("PASS runtime mapping reset sequence");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "timeout");
    end
endmodule
