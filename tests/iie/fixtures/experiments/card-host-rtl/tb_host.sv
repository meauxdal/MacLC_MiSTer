`timescale 1ns/1ps
module tb_host;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, req_valid = 0, req_word = 0, req_write = 0, rsp_ready = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error;
    wire [15:0] rsp_rdata;
    wire mv, mw, mr;
    wire [17:0] ma;
    wire [15:0] md;
    wire [1:0] mb;
    reg mrv = 0;
    reg [15:0] mrd = 0;
    wire [7:0] control;
    wire [15:0] index;
    wire sidefx_valid;
    wire [5:0] sidefx_offset;
    wire sidefx_word, sidefx_write;
    wire [15:0] sidefx_wdata;
    wire ack, release_read, address_read, control_write, command_write, mask_write, key_write;
    integer cycles = 0, memory_ops = 0, side_effects = 0, transactions = 0;
    integer latency = -1;
    reg [17:0] held_ma;
    reg [15:0] held_md;
    reg [1:0] held_mb;
    reg held_mw;
    wire mem_ready = latency == -1 && !mrv && cycles % 3 != 0;
    reg [7:0] memory [0:262143];
    reg [7:0] expected_memory [0:262143];
    reg [1023:0] stimulus_path, expected_path;
    integer file, scan, w, word_access, offset, value, error_value, i, pause_count;
    reg [16:0] response;
    card_host_registers dut (
        .clk(clk), .reset(reset), .req_valid(req_valid), .req_ready(req_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_req_valid(mv), .mem_req_ready(mem_ready), .mem_req_addr(ma), .mem_req_write(mw),
        .mem_req_wdata(md), .mem_req_be(mb), .mem_rsp_valid(mrv), .mem_rsp_ready(mr),
        .mem_rsp_rdata(mrd), .mem_rsp_denied(1'b0), .control(control), .index(index),
        .capture_status(8'hE1), .capture_address(16'h0000), .capture_data(8'h17),
        .keyboard_status(8'h80), .opaque08(8'h00),
        .sidefx_valid(sidefx_valid), .sidefx_offset(sidefx_offset), .sidefx_word(sidefx_word),
        .sidefx_write(sidefx_write), .sidefx_wdata(sidefx_wdata),
        .ack_write(ack), .read_release_write(release_read), .capture_address_read(address_read),
        .control_write(control_write), .command_write(command_write), .mask_write(mask_write),
        .keyboard_write(key_write)
    );
    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > 60000000) $fatal(1, "cycle bound");
        if (sidefx_valid) side_effects = side_effects + 1;
        if (mrv && mr) mrv <= 0;
        if (mv && mem_ready) begin
            if (mb !== (ma[0] ? 2'b10 : 2'b01)) $fatal(1, "byte enables");
            held_ma <= ma; held_md <= md; held_mb <= mb; held_mw <= mw;
            latency <= memory_ops % 6;
            memory_ops = memory_ops + 1;
        end else if (latency > 0) latency <= latency - 1;
        else if (latency == 0) begin
            latency <= -1;
            mrv <= 1;
            mrd <= {memory[{held_ma[17:1], 1'b1}], memory[{held_ma[17:1], 1'b0}]};
            if (held_mw) begin
                if (held_mb[0]) memory[{held_ma[17:1], 1'b0}] <= held_md[7:0];
                if (held_mb[1]) memory[{held_ma[17:1], 1'b1}] <= held_md[15:8];
            end
        end
    end
    initial begin
        if (!$value$plusargs("stimulus=%s", stimulus_path)) $fatal(1, "missing stimulus");
        if (!$value$plusargs("expected=%s", expected_path)) $fatal(1, "missing expected");
        for (i = 0; i < 262144; i = i + 1) memory[i] = 0;
        $readmemh(expected_path, expected_memory);
        file = $fopen(stimulus_path, "r");
        repeat (3) @(negedge clk);
        reset = 0;
        while (!$feof(file)) begin
            scan = $fscanf(file, "%h %h %h %h %h\n", w, word_access, offset, value, error_value);
            if (scan != 5) $fatal(1, "bad stimulus line");
            @(negedge clk);
            req_valid = 1; req_write = w[0]; req_word = word_access[0];
            req_offset = offset[5:0]; req_wdata = w ? value[15:0] : 16'hDEAD;
            while (!req_ready) @(negedge clk);
            @(negedge clk); req_valid = 0;
            while (!rsp_valid) @(negedge clk);
            if (rsp_error !== error_value[0]) $fatal(1, "response error at %0d", transactions);
            if (!w && !error_value && rsp_rdata !== value[15:0])
                $fatal(1, "read %0d +%h got %h expected %h", transactions, offset, rsp_rdata, value);
            response = {rsp_error, rsp_rdata};
            pause_count = transactions % 4;
            repeat (pause_count) begin
                @(negedge clk);
                if (!rsp_valid || {rsp_error, rsp_rdata} !== response || req_ready)
                    $fatal(1, "response backpressure");
            end
            rsp_ready = 1;
            @(negedge clk); rsp_ready = 0;
            transactions = transactions + 1;
        end
        for (i = 0; i < 262144; i = i + 1)
            if (memory[i] !== expected_memory[i]) $fatal(1, "memory mismatch %h", i);
        $display("PASS transactions=%0d memory_ops=%0d side_effects=%0d cycles=%0d index=%h control=%h",
                 transactions, memory_ops, side_effects, cycles, index, control);
        $finish;
    end
endmodule
