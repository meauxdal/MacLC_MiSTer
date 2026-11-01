`timescale 1ns/1ps
module tb_diagnostic;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1;
    reg ready = 0;
    reg [7:0] data;
    wire valid, write, sync, vector_pull, hr, hw;
    wire [15:0] address;
    wire [16:0] ram_address;
    wire [7:0] write_data;
    card_cpu_bus dut (
        .clk(clk), .reset(reset), .ready(ready), .read_data(data),
        .irq_n(1'b1), .nmi_n(1'b1), .valid(valid), .address(address),
        .ram_address(ram_address), .write(write), .write_data(write_data),
        .sync(sync), .vector_pull(vector_pull),
        .high_ram_read(hr), .high_ram_write(hw)
    );
    reg [7:0] memory [0:262143];
    reg [7:0] expected_memory [0:262143];
    reg [1023:0] image, trace_path;
    integer trace_file, i, cycles = 0, completed = 0, captures = 0;
    integer countdown = -1, delay_scale = 1, physical;
    integer writes = 0, display_writes = 0, stack_writes = 0;
    reg [25:0] held;
    reg trapped, report_mode = 0;
    reg [7:0] status;

    function is_display(input [15:0] a);
        is_display = a == 16'h0400 || a == 16'h0800 ||
                     a == 16'h2000 || a == 16'h4000;
    endfunction
    function [7:0] display_status(input [15:0] a);
        case (a)
            16'h0400: display_status = 8'h02;
            16'h0800: display_status = 8'h22;
            16'h2000: display_status = 8'h04;
            16'h4000: display_status = 8'h24;
            default: display_status = 0;
        endcase
    endfunction

    initial begin
        if (!$value$plusargs("image=%s", image)) $fatal(1, "missing image");
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1, "missing trace");
        if (!$value$plusargs("delay=%d", delay_scale)) delay_scale = 1;
        $readmemh(image, memory);
        for (i = 0; i < 262144; i = i + 1) begin
            expected_memory[i] = memory[i];
        end
        expected_memory[18'h001FD] = 8'h20;
        expected_memory[18'h001FC] = 8'h1C;
        expected_memory[18'h00400] = 8'h17;
        expected_memory[18'h00800] = 8'h17;
        expected_memory[18'h02000] = 8'h17;
        expected_memory[18'h04000] = 8'h17;
        expected_memory[18'h10400] = 8'h17;
        expected_memory[18'h10800] = 8'h17;
        expected_memory[18'h12000] = 8'h17;
        expected_memory[18'h14000] = 8'h17;
        trace_file = $fopen(trace_path, "w");
        repeat (3) @(negedge clk);
        reset = 0;
    end

    always @(negedge clk) begin
        if (!reset && valid) begin
            if (sync && address == 16'h201D) begin
                if (captures != 29 || display_writes != 16 || stack_writes != 4)
                    $fatal(1, "wrong counts %0d %0d %0d", captures, display_writes, stack_writes);
                if (dut.cpu.reg_s !== 8'hFD) $fatal(1, "stack not restored");
                for (i = 0; i < 262144; i = i + 1)
                    if (memory[i] !== expected_memory[i]) $fatal(1, "memory mismatch %h", i);
                $display("PASS cycles=%0d completed=%0d captures=%0d writes=%0d SP=%h",
                         cycles, completed, captures, writes, dut.cpu.reg_s);
                $fclose(trace_file);
                $finish;
            end
            if (sync && address == 16'h201A) report_mode = 1;
            physical = address >= 16'hFFFA ? 18'h23FFA + address - 16'hFFFA : ram_address;
            data = address == 16'hC07D ? 8'hA5 :
                   address == 16'hC0E9 ? 8'h17 : memory[physical];
            trapped = (vector_pull && address == 16'hFFFC) ||
                      address == 16'hC07D || address == 16'hC0E9 ||
                      (write && is_display(address));
            status = vector_pull && address == 16'hFFFC ? 8'h80 :
                     address == 16'hC07D ? (write ? 8'hE0 : 8'hE1) :
                     address == 16'hC0E9 ? 8'h38 :
                     display_status(address) | (ram_address[16] ? 8'h08 : 0) |
                     (report_mode ? 1 : 0);
            if (countdown == -1) begin
                held = {address, write_data, write, sync};
                countdown = delay_scale * (trapped ? 1002 : (completed % 8));
                if (trapped) begin
                    $fdisplay(trace_file, "%02x %04x %0d %0d %02x", status, address,
                              write, ram_address[16], write ? write_data : data);
                    captures = captures + 1;
                end
            end else if (held !== {address, write_data, write, sync})
                $fatal(1, "bus changed before completion");
            ready = countdown == 0;
            if (countdown > 0) countdown = countdown - 1;
        end else ready = 0;
    end

    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > 100000) $fatal(1, "cycle bound");
        if (valid && ready) begin
            completed = completed + 1;
            countdown = -1;
            if (write) begin
                writes = writes + 1;
                if (address < 16'hC000) begin
                    memory[ram_address] = write_data;
                    if (is_display(address)) begin
                        display_writes = display_writes + 1;
                        if (write_data !== (report_mode ? 8'h17 : 8'hA5))
                            $fatal(1, "display data");
                    end else if (address == 16'h01FD || address == 16'h01FC)
                        stack_writes = stack_writes + 1;
                    else $fatal(1, "unexpected RAM write %h", address);
                end else if (address != 16'hC004 && address != 16'hC005 &&
                             address != 16'hC07D && address != 16'hC0E9)
                    $fatal(1, "unexpected I/O write");
            end
        end
    end
endmodule
