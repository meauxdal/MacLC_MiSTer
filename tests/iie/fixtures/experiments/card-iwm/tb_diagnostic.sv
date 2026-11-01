`timescale 1ns/1ps
module tb_diagnostic;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, ready = 0;
    wire valid, write, sync, vector_pull, halted, high_read, high_write;
    wire [15:0] address;
    wire [16:0] ram_address;
    wire [7:0] write_data, read_data, iwm_data;
    wire selected = address[15:4] == 12'hC0E;
    wire complete = valid && ready;
    wire [3:0] phases;
    wire motor, drive_select, q6, q7, data_read, data_write;
    wire [4:0] mode;
    card_cpu_bus processor (
        .clk(clk), .reset(reset), .ready(ready), .read_data(read_data),
        .irq_n(1'b1), .nmi_n(1'b1), .valid(valid), .address(address),
        .ram_address(ram_address), .write(write), .write_data(write_data),
        .sync(sync), .vector_pull(vector_pull), .halted(halted),
        .high_ram_read(high_read), .high_ram_write(high_write)
    );
    card_iwm_frontend controller (
        .clk(clk), .reset(reset), .complete(complete), .selected(selected),
        .address(address[3:0]), .write(write), .write_data(write_data),
        .drive_data(8'hA5), .drive_sense(1'b1), .write_busy(1'b0), .write_underrun(1'b0),
        .read_data(iwm_data), .phases(phases), .motor(motor), .drive_select(drive_select),
        .q6(q6), .q7(q7), .mode(mode), .data_read(data_read), .data_write(data_write), .data_out()
    );
    reg [7:0] memory [0:262143], expected [0:262143];
    assign read_data = vector_pull && address == 16'hFFFC ? 8'h00 :
                       vector_pull && address == 16'hFFFD ? 8'h02 :
                       selected ? iwm_data : memory[{1'b0, ram_address}];
    reg [1023:0] image, trace;
    integer i, file, clocks = 0, cycles = 0, io_cycles = 0, stack_writes = 0;
    integer countdown = -1, delay_scale = 0;
    reg [25:0] held;
    initial begin
        if (!$value$plusargs("image=%s", image) || !$value$plusargs("trace=%s", trace))
            $fatal(1, "missing image/trace");
        if (!$value$plusargs("delay=%d", delay_scale)) delay_scale = 0;
        $readmemh(image, memory);
        memory[16'h0200] = 8'h20;
        memory[16'h0201] = 8'h63;
        memory[16'h0202] = 8'h21;
        memory[16'h0203] = 8'hEA;
        for (i = 0; i < 262144; i = i + 1) expected[i] = memory[i];
        expected[16'h01FD] = 8'h02;
        expected[16'h01FC] = 8'h02;
        file = $fopen(trace, "w");
        repeat (3) @(negedge clk); reset = 0;
    end
    always @(negedge clk) begin
        if (!reset && valid) begin
            if (sync && address == 16'h0203) begin
                if (processor.cpu.reg_x !== 0) $fatal(1, "original IWM diagnostic failed X=%h", processor.cpu.reg_x);
                if (io_cycles != 12 || stack_writes != 2 || mode != 0 || q6 != 1 || q7 != 0 || motor)
                    $fatal(1, "IWM diagnostic counts/final state");
                if (processor.cpu.reg_s !== 8'hFD) $fatal(1, "stack not restored");
                for (i = 0; i < 262144; i = i + 1)
                    if (memory[i] !== expected[i]) $fatal(1, "memory mismatch %h", i);
                $display("PASS original IWM diagnostic X=00 cycles=%0d io=%0d stack_writes=%0d clocks=%0d", cycles, io_cycles, stack_writes, clocks);
                $fclose(file); $finish;
            end
            if (countdown == -1) begin
                held = {address, write_data, write, sync};
                countdown = delay_scale * ((cycles % 7) + (selected ? 19 : 0));
            end else if (held !== {address, write_data, write, sync})
                $fatal(1, "CPU bus changed during held access");
            ready = countdown == 0;
            if (countdown > 0) countdown = countdown - 1;
        end else ready = 0;
    end
    always @(posedge clk) begin
        clocks = clocks + 1;
        if (clocks > 10000 || halted) $fatal(1, "CPU watchdog/halt");
        if (complete) begin
            cycles = cycles + 1;
            countdown = -1;
            if (selected) begin
                io_cycles = io_cycles + 1;
                $fdisplay(file, "%04x %0d %02x %02x", address, write, write_data, read_data);
            end else if (write) begin
                if (address != 16'h01FC && address != 16'h01FD) $fatal(1, "unexpected RAM write %h", address);
                memory[ram_address] = write_data;
                stack_writes = stack_writes + 1;
            end
        end
    end
endmodule
