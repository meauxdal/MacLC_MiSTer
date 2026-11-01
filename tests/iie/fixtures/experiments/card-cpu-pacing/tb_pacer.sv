`timescale 1ns/1ps
module tb_pacer;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, fast = 0, allow = 1;
    wire due;
    integer count = 0, i;
    card_cycle_pacer #(.CLOCK_HZ(100), .NORMAL_HZ(13), .FAST_HZ(23)) dut (
        .clk(clk), .reset(reset), .fast(fast), .complete(due && allow), .due(due)
    );
    task tick;
        begin
            @(posedge clk);
            if (due && allow) count = count + 1;
            @(negedge clk);
        end
    endtask
    initial begin
        tick();
        reset = 0;
        for (i = 0; i < 1000; i = i + 1) tick();
        if (count != 130) $fatal(1, "normal fractional rate %0d", count);
        reset = 1; fast = 1; tick(); reset = 0; count = 0;
        for (i = 0; i < 1000; i = i + 1) tick();
        if (count != 230) $fatal(1, "fast fractional rate %0d", count);
        allow = 0;
        for (i = 0; i < 100; i = i + 1) tick();
        if (!due) $fatal(1, "lost overdue enable");
        fast = 0;
        for (i = 0; i < 10; i = i + 1) begin
            tick();
            if (!due) $fatal(1, "speed change canceled overdue cycle");
        end
        allow = 1; tick(); count = 0;
        for (i = 0; i < 7; i = i + 1) tick();
        if (count != 0) $fatal(1, "catch-up or early normal enable");
        tick();
        if (count != 1) $fatal(1, "missing normal enable after switch");
        reset = 1; tick();
        if (due) $fatal(1, "reset enable");
        reset = 0; count = 0;
        for (i = 0; i < 7; i = i + 1) tick();
        if (count != 0) $fatal(1, "reset retained old phase");
        $display("PASS fractional rates, overdue hold, no catch-up, speed boundary, reset");
        $finish;
    end
endmodule
