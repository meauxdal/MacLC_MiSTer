module tb_keyboard;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, host_write = 0, cpu_complete = 0;
    reg [6:0] host_data = 0;
    reg [15:0] cpu_address = 0;
    wire [7:0] keyboard;
    wire busy;
    integer value, pause_cycle, checks = 0;
    card_keyboard_candidate dut(.*);

    task tick;
        begin @(posedge clk); #1; end
    endtask
    task check(input [7:0] expected);
        begin
            if (keyboard !== expected || busy !== expected[7])
                $fatal(1, "keyboard expected=%h actual=%h", expected, keyboard);
            checks = checks + 1;
            @(negedge clk);
        end
    endtask

    initial begin
        tick(); check(0); reset = 0;
        for (value = 0; value < 128; value = value + 1) begin
            host_data = 7'(value); host_write = 1;
            tick(); check(8'(128 + (value % 128))); host_write = 0;
            cpu_address = 16'hC010;
            for (pause_cycle = 0; pause_cycle < 3; pause_cycle = pause_cycle + 1) begin
                tick(); check(8'(128 + (value % 128)));
            end
            cpu_complete = 1; cpu_address = 16'hC000;
            tick(); check(8'(128 + (value % 128)));
            cpu_address = 16'hC010;
            tick(); check(8'(value % 128)); cpu_complete = 0;
            tick(); check(8'(value % 128));
        end
        host_write = 1; host_data = 7'h5A; cpu_complete = 1;
        tick(); check(8'hDA);
        reset = 1;
        tick(); check(0);
        $display("PASS characters=128 stalled_clear=3 checks=%0d", checks);
        $finish;
    end
endmodule
