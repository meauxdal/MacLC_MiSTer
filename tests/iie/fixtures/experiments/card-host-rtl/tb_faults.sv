`timescale 1ns/1ps
module tb_faults;
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
    reg mrv = 0, denied = 0;
    reg [15:0] mrd = 0;
    wire [7:0] control;
    wire [15:0] index;
    wire sidefx_valid;
    wire [5:0] sidefx_offset;
    wire sidefx_word, sidefx_write;
    wire [15:0] sidefx_wdata;
    wire ack, release_read, address_read, control_write, command_write, mask_write, key_write;
    reg [7:0] memory [0:262143];
    integer ops = 0, cycles = 0, i;
    integer acks = 0, releases = 0, addresses = 0, controls = 0;
    integer commands = 0, masks = 0, keys = 0;
    card_host_registers dut (
        .clk(clk), .reset(reset), .req_valid(req_valid), .req_ready(req_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_req_valid(mv), .mem_req_ready(!mrv), .mem_req_addr(ma), .mem_req_write(mw),
        .mem_req_wdata(md), .mem_req_be(mb), .mem_rsp_valid(mrv), .mem_rsp_ready(mr),
        .mem_rsp_rdata(mrd), .mem_rsp_denied(denied), .control(control), .index(index),
        .capture_status(8'hE1), .capture_address(16'hC07D), .capture_data(8'h17),
        .keyboard_status(8'h80), .opaque08(8'h56),
        .sidefx_valid(sidefx_valid), .sidefx_offset(sidefx_offset), .sidefx_word(sidefx_word),
        .sidefx_write(sidefx_write), .sidefx_wdata(sidefx_wdata), .ack_write(ack),
        .read_release_write(release_read), .capture_address_read(address_read),
        .control_write(control_write), .command_write(command_write), .mask_write(mask_write),
        .keyboard_write(key_write)
    );
    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > 1000) $fatal(1, "cycle bound");
        if (ack) acks = acks + 1;
        if (release_read) releases = releases + 1;
        if (address_read) addresses = addresses + 1;
        if (control_write) controls = controls + 1;
        if (command_write) commands = commands + 1;
        if (mask_write) masks = masks + 1;
        if (key_write) keys = keys + 1;
        if (mrv && mr) mrv <= 0;
        if (mv && !mrv) begin
            ops = ops + 1;
            if (mb !== (ma[0] ? 2'b10 : 2'b01)) $fatal(1, "enables");
            mrv <= 1;
            denied <= ops == 2 || ops == 7;
            mrd <= {memory[{ma[17:1], 1'b1}], memory[{ma[17:1], 1'b0}]};
            if (mw && ops != 2 && ops != 7) begin
                if (mb[0]) memory[{ma[17:1], 1'b0}] <= md[7:0];
                if (mb[1]) memory[{ma[17:1], 1'b1}] <= md[15:8];
            end
        end
    end
    task transfer(input w, input word_access, input [5:0] offset,
                  input [15:0] value, input error_value);
        reg [16:0] held;
        begin
            @(negedge clk);
            req_valid = 1; req_write = w; req_word = word_access;
            req_offset = offset; req_wdata = value;
            while (!req_ready) @(negedge clk);
            @(negedge clk); req_valid = 0;
            while (!rsp_valid) @(negedge clk);
            if (rsp_error !== error_value || (!w && !error_value && rsp_rdata !== value))
                $fatal(1, "response +%h got %h/%b", offset, rsp_rdata, rsp_error);
            held = {rsp_error, rsp_rdata};
            repeat (3) begin
                @(negedge clk);
                if (!rsp_valid || {rsp_error, rsp_rdata} !== held || req_ready)
                    $fatal(1, "backpressure");
            end
            rsp_ready = 1;
            @(negedge clk); rsp_ready = 0;
        end
    endtask
    initial begin
        for (i = 0; i < 262144; i = i + 1) memory[i] = 0;
        repeat (3) @(negedge clk); reset = 0;
        transfer(1, 0, 6'h0D, 16'h0008, 0);
        transfer(1, 1, 6'h1C, 16'hFFFF, 0);
        transfer(1, 1, 6'h10, 16'h12AB, 1);
        if (memory[18'h2FFFF] != 8'h12 || memory[18'h3FFFF] != 0)
            $fatal(1, "denied second lane contract");
        transfer(0, 1, 6'h1C, 16'hFFFF, 0);
        transfer(1, 1, 6'h10, 16'h12AB, 0);
        transfer(0, 1, 6'h1C, 0, 0);
        transfer(1, 1, 6'h1C, 16'hFFFF, 0);
        transfer(0, 1, 6'h10, 16'h12AB, 0);
        transfer(1, 0, 6'h10, 16'h00CD, 1);
        transfer(0, 1, 6'h1C, 0, 0);
        if (memory[18'h20000] != 0) $fatal(1, "denied byte changed RAM");
        transfer(1, 0, 6'h10, 16'h00CD, 0);
        transfer(0, 1, 6'h1C, 1, 0);
        transfer(1, 1, 6'h11, 16'h1234, 1);
        transfer(0, 0, 6'h01, 16'h00E1, 0);
        transfer(0, 1, 6'h04, 16'hC07D, 0);
        transfer(0, 0, 6'h08, 16'h0056, 0);
        transfer(0, 0, 6'h09, 16'h0080, 0);
        transfer(0, 0, 6'h0C, 16'h0017, 0);
        transfer(1, 0, 6'h0C, 0, 0);
        transfer(1, 0, 6'h19, 0, 0);
        transfer(1, 0, 6'h18, 16'h0080, 0);
        transfer(1, 0, 6'h20, 16'h0088, 0);
        transfer(1, 1, 6'h20, 16'h0802, 0);
        transfer(1, 0, 6'h21, 16'h00FC, 0);
        transfer(1, 0, 6'h22, 0, 1);
        if (acks != 1 || releases != 1 || addresses != 1 || controls != 1 ||
            commands != 2 || masks != 1 || keys != 1 || ops != 8)
            $fatal(1, "side effect count");
        if (control != 8 || index != 1) $fatal(1, "latch state");
        $display("PASS denied lanes, wrap, read snapshots, decoded strobes, unsupported accesses, response stalls");
        $finish;
    end
endmodule
