`timescale 1ns/1ps
module tb_card_pds_adapter;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1;
    reg [31:0] cpu_address = 0;
    reg [2:0] cpu_fc = 1;
    reg cpu_as_n = 1, cpu_uds_n = 1, cpu_lds_n = 1, cpu_rw = 1;
    reg [15:0] cpu_write_data = 0;
    wire claim, dtack_n, error;
    wire [15:0] cpu_read_data;
    wire req_valid, rsp_ready;
    reg req_ready = 0, rsp_valid = 0, rsp_error = 0;
    wire [5:0] req_offset;
    wire req_word, req_write;
    wire [15:0] req_wdata;
    reg [15:0] rsp_rdata = 0;
    integer requests = 0, responses = 0, completed = 0;
    integer i, lane, direction;
    reg [31:0] bases [0:2];
    card_pds_adapter dut (.*);
    always @(posedge clk) begin
        if (req_valid && req_ready) requests <= requests + 1;
        if (rsp_valid && rsp_ready) responses <= responses + 1;
    end
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task idle;
        begin
            cpu_as_n = 1;
            cpu_uds_n = 1;
            cpu_lds_n = 1;
            tick;
            if (claim || !dtack_n || req_valid || rsp_ready || error) $fatal(1, "idle outputs");
        end
    endtask
    task start_cycle(input [31:0] address, input [1:0] strobes, input wr);
        begin
            cpu_address = address;
            cpu_uds_n = strobes[1];
            cpu_lds_n = strobes[0];
            cpu_write_data = 16'hA63D;
            cpu_rw = !wr;
            cpu_as_n = 0;
            #1;
        end
    endtask
    task accept_request;
        begin
            req_ready = 1;
            tick;
            req_ready = 0;
            if (req_valid || !rsp_ready || !dtack_n) $fatal(1, "accept handshake");
        end
    endtask
    task respond(input [15:0] data, input failed);
        begin
            rsp_rdata = data;
            rsp_error = failed;
            rsp_valid = 1;
            tick;
            rsp_valid = 0;
            rsp_error = 0;
        end
    endtask
    task transfer(input [31:0] address, input [1:0] strobes,
                  input wr, input [5:0] offset, input word_access,
                  input [15:0] data, input [15:0] reply);
        integer n, before_requests;
        begin
            before_requests = requests;
            start_cycle(address, strobes, wr);
            if (!claim || !dtack_n) $fatal(1, "early claim/DTACK");
            tick;
            for (n = 0; n < 4; n = n + 1) begin
                if (!req_valid || req_offset !== offset || req_word !== word_access ||
                    req_write !== wr || req_wdata !== data || !dtack_n || !claim)
                    $fatal(1, "stalled request fields");
                tick;
            end
            accept_request;
            repeat (4) begin
                tick;
                if (!dtack_n || !claim || !rsp_ready || req_valid) $fatal(1, "response stall");
            end
            respond(16'hB752, 0);
            if (dtack_n || !claim || error || cpu_read_data !== reply)
                $fatal(1, "response lane or DTACK");
            rsp_rdata = 16'h1234;
            repeat (6) begin
                tick;
                if (dtack_n || !claim || req_valid || rsp_ready || cpu_read_data !== reply)
                    $fatal(1, "held AS repeated transaction or unstable response");
            end
            if (requests != before_requests + 1) $fatal(1, "duplicate request");
            completed = completed + 1;
            idle;
        end
    endtask
    initial begin
        bases[0] = 32'h80000000;
        bases[1] = 32'h80E00000;
        bases[2] = 32'h00E00000;
        tick;
        reset = 0;
        idle;
        for (i = 0; i < 3; i = i + 1)
            for (direction = 0; direction < 2; direction = direction + 1) begin
                transfer(bases[i] + 32'h10, 2'b00, direction != 0, 6'h10, 1, 16'hA63D, 16'hB752);
                transfer(bases[i] + 32'h20, 2'b01, direction != 0, 6'h20, 0, 16'h00A6, 16'h52FF);
                transfer(bases[i] + 32'h22, 2'b10, direction != 0, 6'h23, 0, 16'h003D, 16'hFF52);
            end
        // No strobes yet: claim the alias early, but wait for data strobes.
        start_cycle(bases[0], 2'b11, 0);
        repeat (3) begin
            tick;
            if (!claim || req_valid || !dtack_n) $fatal(1, "unstrobed cycle");
        end
        cpu_uds_n = 0;
        tick;
        if (!req_valid || req_offset != 0 || req_word) $fatal(1, "late strobe");
        accept_request;
        respond(16'h0069, 0);
        if (cpu_read_data !== 16'h69FF || dtack_n) $fatal(1, "late-strobe reply");
        idle;
        // CPU-space and odd addresses never claim or request.
        for (i = 0; i < 3; i = i + 1) begin
            cpu_fc = 7;
            start_cycle(bases[i], 2'b00, 0);
            tick;
            if (claim || req_valid || !dtack_n) $fatal(1, "FC7 claimed");
            idle;
            cpu_fc = 1;
            start_cycle(bases[i] + 1, 2'b00, 0);
            tick;
            if (claim || req_valid || !dtack_n) $fatal(1, "odd address claimed");
            idle;
            start_cycle(bases[i] + 32'h24, 2'b00, 0);
            tick;
            if (claim || req_valid || !dtack_n) $fatal(1, "window overrun claimed");
            idle;
        end
        start_cycle(32'h00D00000, 2'b00, 0);
        tick;
        cpu_address = bases[0];
        tick;
        if (claim || req_valid) $fatal(1, "nonclaimed AS cycle rearmed");
        idle;
        // Request fields stay latched even if CPU inputs move during a stall.
        start_cycle(bases[0] + 32'h10, 2'b00, 1);
        tick;
        cpu_address = 0;
        cpu_write_data = 16'h1234;
        cpu_uds_n = 1;
        cpu_lds_n = 1;
        tick;
        if (!claim || !req_valid || req_offset != 6'h10 || req_wdata != 16'hA63D || !req_word)
            $fatal(1, "request changed with CPU inputs");
        reset = 1;
        req_ready = 1;
        tick;
        req_ready = 0;
        if (req_valid || claim || !dtack_n || rsp_ready) $fatal(1, "unaccepted reset cancellation");
        reset = 0;
        tick;
        if (req_valid || claim) $fatal(1, "reset AS rearmed");
        idle;
        // Accepted writes drain across reset without DTACK or a second request.
        start_cycle(bases[1] + 32'h20, 2'b01, 1);
        tick;
        accept_request;
        reset = 1;
        tick;
        if (claim || !dtack_n || !rsp_ready) $fatal(1, "reset lost accepted request");
        reset = 0;
        repeat (4) begin
            tick;
            if (claim || !dtack_n || !rsp_ready || req_valid) $fatal(1, "reset drain");
        end
        respond(0, 0);
        repeat (3) tick;
        if (claim || !dtack_n || req_valid || rsp_ready) $fatal(1, "drained AS rearmed");
        idle;
        // AS withdrawal uses the same drain rule.
        start_cycle(bases[2], 2'b10, 0);
        tick;
        accept_request;
        cpu_as_n = 1;
        tick;
        cpu_as_n = 0;
        tick;
        if (claim || !dtack_n || !rsp_ready) $fatal(1, "AS abort lost response");
        respond(16'h55, 0);
        idle;
        // Backend errors are exposed for BERR policy and never DTACKed.
        start_cycle(bases[0], 2'b00, 0);
        tick;
        accept_request;
        respond(16'hDEAD, 1);
        repeat (4) begin
            tick;
            if (!claim || !error || !dtack_n || req_valid || rsp_ready || cpu_read_data != 16'hDEAD)
                $fatal(1, "backend error response");
        end
        reset = 1;
        tick;
        if (claim || error || !dtack_n) $fatal(1, "completed reset");
        reset = 0;
        idle;
        if (requests != responses || requests != 22) $fatal(1, "transaction totals %0d/%0d", requests, responses);
        $display("PASS PDS adapter: %0d lane transfers, %0d requests drained", completed, requests);
        $finish;
    end
    initial begin #100000; $fatal(1, "test timeout"); end
endmodule
