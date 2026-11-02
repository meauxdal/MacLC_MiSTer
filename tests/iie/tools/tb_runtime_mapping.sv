`timescale 1ns/1ps
module tb_runtime_mapping;
    reg clk = 0, por_n = 0, runtime_mode = 0;
    always #5 clk = !clk;
    reg req_valid = 0, req_word = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error;
    wire [3:0] debug_state;
    wire [71:0] debug_trace;
    card_irq_candidate dut (
        .clk(clk), .por_n(por_n), .runtime_mode(runtime_mode),
        .req_valid(req_valid), .req_ready(req_ready), .req_offset(req_offset),
        .req_word(req_word), .req_write(1'b1), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1), .rsp_error(rsp_error),
        .mem_ready(1'b0), .mem_rsp_valid(1'b0), .mem_rdata(16'b0),
        .debug_state(debug_state), .debug_trace(debug_trace)
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
    task check_mapping(input expected, input [15:0] trace);
        begin
            repeat (8) @(posedge clk);
            if (debug_state[3] !== expected) $fatal(1, "mapping mismatch");
            if (debug_trace[15:0] !== trace) $fatal(1, "start trace mismatch actual=%h expected=%h", debug_trace[15:0], trace);
        end
    endtask
    initial begin
        force dut.cpu_valid = 0;
        repeat (4) @(posedge clk);
        @(negedge clk); por_n = 1;
        write_reg(6'h20, 0, 16'h0088);
        check_mapping(0, 16'h0000);
        if (dut.fault || dut.armed || dut.cpu_running || dut.start_pending)
            $fatal(1, "stopped run command changed reset state");
        if (debug_trace[71:16] !== 56'h00880000000000)
            $fatal(1, "stopped command context mismatch");
        write_reg(6'h20, 0, 16'h00A8);
        check_mapping(0, 16'h0000);
        if (dut.fault || dut.armed || dut.cpu_running || dut.start_pending)
            $fatal(1, "stopped IRQ command changed reset state");
        write_reg(6'h21, 0, 16'h00FC);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(0, 16'hFC10);
        write_reg(6'h20, 1, 16'h0802);
        check_mapping(0, 16'hFC10);
        write_reg(6'h20, 0, 16'h0088);
        check_mapping(0, 16'hFC10);
        if (dut.fault || dut.armed || dut.cpu_running || dut.start_pending)
            $fatal(1, "post-cleanup command restarted CPU");
        write_reg(6'h21, 0, 16'h0023);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(1, 16'h2320);
        write_reg(6'h20, 1, 16'h0802);
        check_mapping(1, 16'h2320);
        write_reg(6'h21, 0, 16'h00FC);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(0, 16'hFC30);
        runtime_mode = 1;
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(1, 16'hFCC0);
        runtime_mode = 0;
        check_mapping(1, 16'hFCC0);
        write_reg(6'h20, 0, 16'h0088);
        check_mapping(1, 16'hFCC5);
        if (debug_trace[71:16] !== 56'h0088FC60000000)
            $fatal(1, "unarmed command context mismatch actual=%h", debug_trace[71:16]);
        write_reg(6'h20, 0, 16'h0012);
        check_mapping(1, 16'hFCC5);
        if (!dut.fault) $fatal(1, "unarmed command did not fault");
        write_reg(6'h20, 1, 16'h0802);
        write_reg(6'h21, 0, 16'h0023);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(1, 16'hFCC5);
        if (debug_trace[71:16] !== 56'h0088FC60000000)
            $fatal(1, "cleanup overwrote first-fault command context");
        @(negedge clk); por_n = 0;
        repeat (4) @(posedge clk);
        if (debug_trace !== 0 || dut.fault) $fatal(1, "cold reset retained fault trace");
        @(negedge clk); por_n = 1;
        write_reg(6'h21, 0, 16'h00FC);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(0, 16'hFC10);
        write_reg(6'h20, 0, 16'h00A8);
        check_mapping(0, 16'hFC15);
        if (debug_trace[71:16] !== 56'h00A8FC20000000)
            $fatal(1, "diagnostic run context mismatch");
        write_reg(6'h20, 1, 16'h0802);
        write_reg(6'h21, 0, 16'h0023);
        write_reg(6'h20, 0, 16'h0080);
        check_mapping(1, 16'hFC15);
        if (debug_trace[71:16] !== 56'h00A8FC20000000)
            $fatal(1, "runtime restart overwrote diagnostic fault context");
        $display("PASS runtime mapping, sampled start context and sticky first-fault trace");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "timeout");
    end
endmodule
