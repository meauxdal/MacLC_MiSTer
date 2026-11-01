`timescale 1ns/1ps
module tb_iwm;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, complete = 0, selected = 0, write = 0;
    reg [3:0] address = 0;
    reg [7:0] write_data = 0, drive_data = 8'hA5;
    reg drive_sense = 0, write_busy = 0, write_underrun = 0;
    wire [7:0] read_data, data_out;
    wire [3:0] phases;
    wire motor, drive_select, q6, q7, data_read, data_write;
    wire [4:0] mode;
    integer reads = 0, writes = 0, i;
    reg [12:0] held;
    card_iwm_frontend dut (.*);
    always @(posedge clk) begin
        if (data_read) reads = reads + 1;
        if (data_write) writes = writes + 1;
    end
    task access;
        input [3:0] addr;
        input writing;
        input [7:0] value;
        begin
            @(negedge clk);
            selected = 1; address = addr; write = writing; write_data = value;
            held = {mode, phases, motor, drive_select, q6, q7};
            repeat (19) begin
                @(negedge clk);
                if ({mode, phases, motor, drive_select, q6, q7} !== held || data_read || data_write)
                    $fatal(1, "held transaction committed before complete");
            end
            complete = 1;
            @(negedge clk); complete = 0; selected = 0;
        end
    endtask
    initial begin
        repeat (3) @(negedge clk); reset = 0;
        for (i = 0; i < 8; i = i + 1) begin
            access(i[3:0], i[0], 0);
            if (phases[i / 2] !== i[0]) $fatal(1, "phase decode");
        end
        access(4'hB, 0, 0);
        if (!drive_select) $fatal(1, "drive select");
        access(4'hA, 1, 0);
        if (drive_select) $fatal(1, "drive deselect");
        access(4'hD, 0, 0);
        access(4'hF, 1, 8'hFF);
        if (mode != 5'h1F || q6 != 1 || q7 != 1) $fatal(1, "mode write");
        // The Q7-low read selects status during that same transaction.
        @(negedge clk); selected = 1; address = 4'hE; write = 0;
        #1;
        if (read_data != 8'h1F) $fatal(1, "status did not use Q7 next state");
        selected = 0;
        access(4'hE, 0, 0);
        drive_sense = 1;
        #1;
        if (read_data != 8'h9F) $fatal(1, "status sense input");
        access(4'hF, 1, 8'h00);
        if (mode != 0) $fatal(1, "mode clear");
        access(4'hE, 0, 0);
        for (i = 0; i < 32; i = i + 1) begin
            access(4'hF, 1, 8'hE0 | i[7:0]);
            access(4'hE, 0, 0);
            if (read_data[4:0] != i[4:0]) $fatal(1, "mode readback pattern %0d", i);
        end
        access(4'hF, 1, 0);
        access(4'hE, 0, 0);
        access(4'h9, 0, 0);
        if (!motor) $fatal(1, "motor on");
        #1;
        if (read_data != 8'hA0) $fatal(1, "status active bit");
        access(4'hF, 1, 8'hE7);
        if (mode != 0 || writes != 1 || data_out != 8'hE7) $fatal(1, "motor-on data write altered mode/data");
        access(4'hC, 0, 0);
        #1;
        if (read_data != 8'hC0) $fatal(1, "handshake idle");
        write_busy = 1; write_underrun = 1;
        #1;
        if (read_data != 0) $fatal(1, "handshake inputs");
        access(4'hE, 0, 0);
        #1;
        if (read_data != 8'hA5 || reads != 1) $fatal(1, "read data/strobe");
        drive_data = 8'h3C;
        #1;
        if (read_data != 8'h3C) $fatal(1, "read data backend disconnected");
        access(4'h8, 0, 0);
        #1;
        if (motor || read_data != 8'hFF) $fatal(1, "motor-off data float");
        @(negedge clk); selected = 0; address = 4'hF; write = 1; write_data = 31; complete = 1;
        @(negedge clk); complete = 0;
        if (mode != 0 || q7) $fatal(1, "unselected access altered state");
        reset = 1; selected = 1; complete = 1;
        @(negedge clk);
        if ({mode, phases, motor, drive_select, q6, q7} != 0 || data_read || data_write)
            $fatal(1, "reset did not override access");
        $display("PASS held completion, switch decode, mode/status, data/handshake, selection, reset");
        $finish;
    end
endmodule
