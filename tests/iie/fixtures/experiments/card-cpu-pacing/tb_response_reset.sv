`timescale 1ns/1ps
module tb_response_reset;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, ready = 0;
    reg [7:0] data = 8'hA5;
    wire valid, completed;
    card_paced_cpu_bus dut (
        .clk(clk), .reset(reset), .fast(1'b0), .ready(ready), .read_data(data),
        .irq_n(1'b1), .nmi_n(1'b1), .valid(valid), .completed(completed),
        .address(), .ram_address(), .write(), .write_data(), .sync(),
        .vector_pull(), .halted(), .high_ram_read(), .high_ram_write()
    );
    initial begin
        repeat (3) @(negedge clk);
        reset = 0; ready = 1;
        @(negedge clk);
        ready = 0; data = 8'h5A;
        if (!dut.response_pending || valid) $fatal(1, "response not retained");
        if (dut.processor.read_data != 8'hA5) $fatal(1, "live data leaked into response");
        reset = 1;
        @(negedge clk);
        if (dut.response_pending || valid || completed) $fatal(1, "reset did not cancel response");
        reset = 0;
        repeat (100) begin
            @(negedge clk);
            if (completed || dut.response_pending) $fatal(1, "stale completion after reset");
        end
        ready = 1;
        @(negedge clk);
        if (!completed && dut.response_pending) $fatal(1, "new overdue response stalled");
        $display("PASS buffered response data and reset cancellation");
        $finish;
    end
endmodule
