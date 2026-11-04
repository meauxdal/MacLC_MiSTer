`timescale 1ns/1ps
module tb_slot_rom;
    reg clk = 0, por_n = 0;
    always #5 clk = !clk;
    reg req_valid = 0, req_word = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error, fault;
    wire mem_valid, mem_write, mem_rsp_ready, capture_valid;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata, cpu_address, capture_address;
    reg mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    reg [15:0] memory [0:131071];
    reg [15:0] probe_address;
    reg probe_write = 0, probe_complete = 0;
    string image;
    integer expansion_reads = 0, hole_stores = 0;
    reg [7:0] hole_value;
    bit control;
    card_irq_candidate dut (
        .clk(clk), .por_n(por_n), .runtime_mode(1'b0),
        .req_valid(req_valid), .req_ready(req_ready), .req_offset(req_offset),
        .req_word(req_word), .req_write(1'b1), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1), .rsp_error(rsp_error),
        .mem_valid(mem_valid), .mem_ready(!mem_rsp_valid), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata), .fault(fault),
        .cpu_address(cpu_address), .capture_valid(capture_valid),
        .capture_address(capture_address)
    );
    always @(posedge clk) begin
        if (fault) begin
            if (control && dut.instruction_address == 16'hC723 && cpu_address == 16'hC9CC && dut.first_fault == 3) begin
                $display("PASS control reproduces PC C723 BUS C9CC F3");
                $finish;
            end
            $fatal(1, "slot fault pc=%h bus=%h", dut.instruction_address, cpu_address);
        end
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (mem_valid && !mem_rsp_valid) begin
            if (mem_write) begin
                memory[mem_addr] <= mem_wdata;
                if (mem_addr == 17'h003BC) begin
                    hole_stores <= hole_stores + 1;
                    hole_value <= dut.cpu_wdata;
                end
            end
            mem_rdata <= memory[mem_addr];
            mem_rsp_valid <= 1;
        end
        if (dut.cpu_ready && dut.external_c8_read) begin
            expansion_reads <= expansion_reads + 1;
            if (dut.physical !== 18'h2F800 + {7'b0, cpu_address[10:0]})
                $fatal(1, "wrong slot-7 expansion address");
        end
    end
    task host(input bit word_access, input [5:0] offset, input [15:0] value);
        begin
            @(negedge clk);
            req_word = word_access; req_offset = offset; req_wdata = value; req_valid = 1;
            do @(posedge clk); while (!req_ready);
            @(negedge clk); req_valid = 0;
            wait(rsp_valid);
            if (rsp_error) $fatal(1, "host write failed");
            @(negedge clk);
        end
    endtask
    task probe(input [15:0] address, input [17:0] physical, input bit complete);
        begin
            @(negedge clk); probe_address = address;
            #1;
            if (dut.physical !== physical || dut.unsupported_cpu)
                $fatal(1, "mapping bus=%h actual=%h expected=%h", address, dut.physical, physical);
            probe_complete = complete;
            @(negedge clk); probe_complete = 0;
        end
    endtask
    initial begin
        if (!$value$plusargs("image=%s", image)) $fatal(1, "missing image");
        control = $test$plusargs("control");
        $readmemh(image, memory);
        force dut.cpu_valid = 0;
        force dut.cpu_address = probe_address;
        force dut.cpu_write = probe_write;
        force dut.cpu_ready = probe_complete;
        repeat (4) @(negedge clk); por_n = 1;
        host(0, 33, 16'h20); host(0, 32, 16'h80);
        for (integer slot = 1; slot <= 7; slot = slot + 1) begin
            // Slot 3 defaults to internal ROM; expose its external window here.
            force dut.slot3_rom = 1;
            probe(16'hC000 + 16'(slot * 256), 18'h2C000 + 18'(slot * 256), 1);
            probe(16'hC9CC, 18'h2C1CC + 18'(slot * 2048), 0);
            probe(16'hCFFE, 18'h2C7FE + 18'(slot * 2048), 0);
        end
        probe(16'hCFFF, 18'h0CFFF, 1);
        if (dut.expansion_slot != 0) $fatal(1, "CFFF did not release slot");
        @(negedge clk); probe_address = 16'hC9CC;
        #1; if (!dut.unsupported_cpu) $fatal(1, "unselected expansion accepted");
        force dut.slot3_rom = 0;
        probe(16'hC300, 18'h20300, 1);
        probe(16'hC9CC, 18'h209CC, 0);
        force dut.internal_rom = 1;
        probe(16'hC700, 18'h20700, 1);
        if (dut.expansion_slot != 0) $fatal(1, "internal ROM selected external slot");
        release dut.internal_rom;
        @(negedge clk); por_n = 0;
        release dut.slot3_rom;
        repeat (4) @(negedge clk);
        if (dut.expansion_slot != 0 || dut.internal_c8) $fatal(1, "cold reset retained selection");
        release dut.cpu_valid;
        release dut.cpu_address;
        release dut.cpu_write;
        release dut.cpu_ready;
        if (control) force dut.external_c8_read = 0;
        por_n = 1;
        host(0, 33, 16'h20); host(0, 32, 16'h80);
        wait(capture_valid);
        if (capture_address != 16'hFFFC) $fatal(1, "missing reset capture");
        host(0, 32, 16'h88); host(0, 12, 0);
        wait(dut.instruction_address == 16'hC9D5);
        if (capture_valid || hole_stores != 1 || memory[17'h003BC][7:0] !== hole_value)
            $fatal(1, "screen-hole store capture/commit mismatch");
        if (control) $fatal(1, "control passed rejected access");
        if (expansion_reads < 9 || dut.card_mode != 0)
            $fatal(1, "original slot-7 expansion prefix incomplete");
        host(1, 32, 16'h0802);
        wait(!dut.reset_pending && !dut.cpu_running);
        @(negedge clk);
        if (dut.expansion_slot != 0 || dut.internal_c8 || dut.cpu_running)
            $fatal(1, "command reset retained selection");
        $display("PASS slots 1-7, CFFF release, internal ROM priority, resets, original C723 -> C9CC -> C9D5");
        $finish;
    end
    initial begin
        #2000000;
        $fatal(1, "slot ROM timeout pc=%h bus=%h capture=%b/%h running=%b slot=%d reads=%d",
               dut.instruction_address, cpu_address, capture_valid, capture_address,
               dut.cpu_running, dut.expansion_slot, expansion_reads);
    end
endmodule
