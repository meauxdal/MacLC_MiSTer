`timescale 1ns/1ps
module tb_cancel;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, ready = 1;
    wire valid, write, sync, vector_pull, hr, hw;
    wire [15:0] address;
    wire [16:0] ram_address;
    wire [7:0] write_data;
    reg [7:0] memory [0:262143];
    reg [1023:0] image;
    wire [17:0] physical = address >= 16'hFFFA
        ? 18'h23FFA + {2'b00, address} - 18'h0FFFA : {1'b0, ram_address};
    wire [7:0] data = address == 16'hC07D ? 8'hA5 : memory[physical];
    integer display_commits = 0, cycles = 0;
    reg [25:0] held;
    card_cpu_bus dut (
        .clk(clk), .reset(reset), .ready(ready), .read_data(data),
        .irq_n(1'b1), .nmi_n(1'b1), .valid(valid), .address(address),
        .ram_address(ram_address), .write(write), .write_data(write_data),
        .sync(sync), .vector_pull(vector_pull),
        .high_ram_read(hr), .high_ram_write(hw)
    );
    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > 4000) $fatal(1, "cycle bound");
        if (valid && ready && write && address < 16'hC000) begin
            memory[ram_address] = write_data;
            if (address == 16'h0400) display_commits = display_commits + 1;
        end
    end
    initial begin
        if (!$value$plusargs("image=%s", image)) $fatal(1, "missing image");
        $readmemh(image, memory);
        repeat (3) @(negedge clk);
        reset = 0;
        @(negedge clk);
        while (!(write && address == 16'h0400)) @(negedge clk);
        ready = 0;
        held = {address, write_data, write, sync};
        repeat (1002) begin
            @(negedge clk);
            if (held !== {address, write_data, write, sync}) $fatal(1, "held write changed");
            if (memory[18'h10400] !== 0) $fatal(1, "write committed early");
        end
        reset = 1;
        ready = 1;
        #1;
        if (valid) $fatal(1, "reset must cancel valid even when ready");
        repeat (3) @(negedge clk);
        if (dut.banks.ramwrt || display_commits) $fatal(1, "reset state");
        reset = 0;
        @(negedge clk);
        while (!(write && address == 16'h0400)) @(negedge clk);
        ready = 0;
        if (display_commits || ram_address != 17'h10400) $fatal(1, "restart state");
        ready = 1;
        @(negedge clk);
        ready = 0;
        if (display_commits != 1 || memory[18'h10400] !== 8'hA5)
            $fatal(1, "write completion count");
        repeat (10) @(negedge clk);
        if (display_commits != 1) $fatal(1, "duplicate commit");
        $display("PASS reset cancels held write; restart commits once");
        $finish;
    end
endmodule
