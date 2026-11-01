`timescale 1ns/1ps
module tb_banking;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, complete = 0, write = 0;
    reg [15:0] address = 0;
    wire [16:0] physical;
    wire hr, hw;
    integer checks = 0;
    iie_banking dut (.clk(clk), .reset(reset), .complete(complete),
        .address(address), .write(write), .ram_address(physical),
        .high_ram_read(hr), .high_ram_write(hw));

    task access(input [15:0] a, input w);
        begin
            @(negedge clk); address = a; write = w; complete = 1;
            @(negedge clk); complete = 0;
        end
    endtask
    task bank(input [15:0] a, input w, input aux);
        begin
            address = a; write = w; #1;
            if (physical[16] !== aux) $fatal(1, "bank %h write %b got %b", a, w, physical[16]);
            checks = checks + 1;
        end
    endtask
    initial begin
        repeat (2) @(negedge clk);
        reset = 0;
        bank(16'h0000, 0, 0); bank(16'h0400, 1, 0);
        bank(16'hD000, 0, 0);
        if (hr || !hw) $fatal(1, "LC reset policy");
        access(16'hC005, 1);
        bank(16'h0400, 1, 1); bank(16'h0400, 0, 0);
        bank(16'h01FD, 1, 0); bank(16'hBFFF, 1, 1);
        access(16'hC003, 1);
        bank(16'h0400, 0, 1); bank(16'h0000, 0, 0);
        access(16'hC009, 1);
        bank(16'h0000, 0, 1); bank(16'h01FF, 1, 1); bank(16'hD000, 0, 1);
        access(16'hC001, 1);
        bank(16'h0400, 0, 0); bank(16'h07FF, 1, 0);
        bank(16'h0800, 1, 1); bank(16'h2000, 0, 1);
        access(16'hC055, 0);
        bank(16'h0400, 0, 1);
        access(16'hC054, 1); access(16'hC057, 0);
        bank(16'h2000, 0, 0); bank(16'h3FFF, 1, 0); bank(16'h4000, 0, 1);
        access(16'hC055, 1);
        bank(16'h2000, 1, 1);
        access(16'hC000, 1); access(16'hC002, 1); access(16'hC004, 1);
        bank(16'h2000, 1, 0); bank(16'h0400, 0, 0);
        access(16'hC003, 0); access(16'hC005, 0); access(16'hC008, 0);
        bank(16'h2000, 0, 0); bank(16'h2000, 1, 0); bank(16'h0000, 0, 1);
        address = 16'hC008; write = 1; complete = 0;
        repeat (1002) @(negedge clk);
        bank(16'h0000, 0, 1);
        access(16'hC082, 0);
        address = 16'hD000; #1;
        if (hr || hw || physical[15:0] != 16'hD000) $fatal(1, "LC ROM mode");
        access(16'hC08B, 0);
        address = 16'hD000; #1;
        if (!hr || hw || physical[15:0] != 16'hC000) $fatal(1, "LC first odd read");
        access(16'hC08B, 0);
        address = 16'hDFFF; #1;
        if (!hr || !hw || physical[15:0] != 16'hCFFF) $fatal(1, "LC second odd read");
        address = 16'hE000; #1;
        if (physical[15:0] != 16'hE000) $fatal(1, "LC common high RAM");
        access(16'hC080, 1);
        address = 16'hD000; #1;
        if (!hr || hw || physical[15:0] != 16'hD000) $fatal(1, "LC even disable");
        access(16'hC081, 1); access(16'hC081, 0);
        address = 16'hD000; #1;
        if (hr || hw) $fatal(1, "LC write must not pre-enable");
        reset = 1;
        @(negedge clk); reset = 0;
        bank(16'h0000, 0, 0); bank(16'h0400, 1, 0);
        $display("PASS banking checks=%0d plus LC sequence and 1002-cycle uncommitted switch", checks);
        $finish;
    end
endmodule
