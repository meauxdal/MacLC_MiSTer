`timescale 1ns/1ps
module tb_card_memory_arbiter;
    parameter bit DUT_HOST_PRIORITY = 0;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0, reset_request = 0;
    wire drained;
    reg [1:0] req_valid = 0, req_write = 0, req_write_allowed = 2'b11;
    wire [1:0] req_ready, rsp_valid;
    reg [1:0] rsp_ready = 2'b11;
    reg [17:0] host_addr = 0, card_addr = 0;
    reg [15:0] host_wdata = 0, card_wdata = 0;
    reg [1:0] host_be = 2'b11, card_be = 2'b11;
    wire [15:0] rsp_rdata, mem_wdata;
    wire rsp_denied, mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    reg mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    reg busy = 0, backend_write, stall_backend = 0;
    reg [16:0] backend_addr;
    reg [15:0] backend_data;
    integer delay_left = 0, tick = 0;
    wire mem_ready = !stall_backend && !busy && !mem_rsp_valid && ((tick % 5) != 0);
    reg [15:0] memory [0:131071];
    reg [15:0] reference_memory [0:131071];
    integer accepted [0:1];
    integer completed [0:1];
    integer launch_tick [0:1];
    integer max_latency = 0, backend_requests = 0, backend_writes = 0;
    reg [15:0] expected_data [0:1];
    reg expected_denied [0:1];
    reg held_mem = 0, held_rsp = 0;
    reg [33:0] held_bundle;
    reg [18:0] held_response;
    integer i, j, addr_index;
    reg [17:0] active_addr;
    reg [15:0] active_data;
    reg [1:0] active_be;
    reg illegal;

    card_memory_arbiter #(.HOST_PRIORITY(DUT_HOST_PRIORITY)) dut (.*);

    always @(posedge clk) begin
        tick <= tick + 1;
        if (por_n) begin
            if (held_mem && (!mem_valid || {mem_write, mem_addr, mem_wdata} !== held_bundle))
                $fatal(1, "Backend request changed under backpressure");
            held_mem <= mem_valid && !mem_ready;
            held_bundle <= {mem_write, mem_addr, mem_wdata};
            if (held_rsp && {rsp_valid, rsp_denied, rsp_rdata} !== held_response)
                $fatal(1, "Master response changed under backpressure");
            held_rsp <= |(rsp_valid & ~rsp_ready);
            held_response <= {rsp_valid, rsp_denied, rsp_rdata};
            if (reset_request && |req_ready) $fatal(1, "Accepted during reset request");
            if (req_ready == 2'b11 || rsp_valid == 2'b11)
                $fatal(1, "Multiple owners");
            for (j = 0; j < 2; j = j + 1) begin
                if (req_valid[j] && req_ready[j]) begin
                    if (accepted[j] != completed[j]) $fatal(1, "Duplicate acceptance");
                    active_addr = (j != 0) ? card_addr : host_addr;
                    active_data = (j != 0) ? card_wdata : host_wdata;
                    active_be = (j != 0) ? card_be : host_be;
                    addr_index = {15'b0, active_addr[17:1]};
                    illegal = (active_be == 0) ||
                              ((active_be == 3 || active_be == 1) && active_addr[0]) ||
                              ((active_be == 2) && !active_addr[0]);
                    expected_denied[j] = illegal || (req_write[j] && !req_write_allowed[j]);
                    expected_data[j] = (req_write[j] || expected_denied[j]) ?
                                       16'b0 : reference_memory[addr_index];
                    if (req_write[j] && !expected_denied[j]) begin
                        if (active_be[0]) reference_memory[addr_index][7:0] = active_data[7:0];
                        if (active_be[1]) reference_memory[addr_index][15:8] = active_data[15:8];
                    end
                    accepted[j] = accepted[j] + 1;
                    launch_tick[j] = tick;
                end
                if (rsp_valid[j] && rsp_ready[j]) begin
                    if (completed[j] >= accepted[j]) $fatal(1, "Unmatched response");
                    if (rsp_denied !== expected_denied[j] || rsp_rdata !== expected_data[j])
                        $fatal(1, "Response mismatch for master %0d", j);
                    completed[j] = completed[j] + 1;
                    if (tick - launch_tick[j] > max_latency)
                        max_latency = tick - launch_tick[j];
                end
            end
            if (mem_valid && mem_ready) begin
                if (busy || mem_rsp_valid) $fatal(1, "Backend overlap");
                busy <= 1;
                backend_addr <= mem_addr;
                backend_data <= mem_wdata;
                backend_write <= mem_write;
                delay_left <= 4;
                backend_requests = backend_requests + 1;
            end
            if (busy) begin
                if (delay_left != 0) delay_left <= delay_left - 1;
                else begin
                    if (backend_write) begin
                        memory[backend_addr] <= backend_data;
                        backend_writes = backend_writes + 1;
                    end
                    mem_rdata <= memory[backend_addr];
                    mem_rsp_valid <= 1;
                    busy <= 0;
                end
            end
            if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        end
    end

    task automatic transact;
        input integer master;
        input wr;
        input [17:0] address;
        input [15:0] value;
        input [1:0] lanes;
        input allow_write;
        input stall_response;
        begin
            @(negedge clk);
            if (master == 0) begin
                host_addr = address; host_wdata = value; host_be = lanes;
            end else begin
                card_addr = address; card_wdata = value; card_be = lanes;
            end
            req_write[master] = wr;
            req_write_allowed[master] = allow_write;
            rsp_ready[master] = !stall_response;
            req_valid[master] = 1;
            @(posedge clk);
            while (!req_ready[master]) @(posedge clk);
            @(negedge clk);
            req_valid[master] = 0;
            wait (rsp_valid[master]);
            if (stall_response) begin
                repeat (4) @(negedge clk);
                rsp_ready[master] = 1;
            end
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    task automatic retire_source;
        input integer master;
        begin
            @(posedge clk);
            while (!req_ready[master]) @(posedge clk);
            @(negedge clk); req_valid[master] = 0;
        end
    endtask

    integer host_before, card_before, writes_before, window_host, window_card;
    initial begin
        accepted[0] = 0; accepted[1] = 0;
        completed[0] = 0; completed[1] = 0;
        for (i = 0; i < 131072; i = i + 1) begin
            memory[i] = 16'h5aa5 ^ i[15:0] ^ {15'b0, i[16]};
            reference_memory[i] = memory[i];
        end
        repeat (3) @(negedge clk);
        por_n = 1;
        transact(0, 1, 0, 16'habcd, 3, 1, 0);
        transact(1, 1, 0, 16'h0012, 1, 1, 1);
        transact(0, 0, 0, 0, 3, 1, 0);
        transact(1, 1, 1, 16'h3400, 2, 1, 0);
        transact(0, 0, 0, 0, 3, 1, 1);
        transact(1, 1, 0, 16'hffff, 3, 0, 0);
        transact(0, 1, 1, 16'hffff, 3, 1, 0);
        transact(0, 0, 0, 0, 3, 1, 0);

        stall_backend = 1;
        fork
            transact(1, 1, 2, 16'h2468, 3, 1, 0);
            begin
                wait (mem_valid);
                repeat (4) begin
                    @(negedge clk);
                    host_addr = host_addr + 2;
                    host_wdata = host_wdata + 1;
                end
                stall_backend = 0;
            end
        join

        // Reset requests drain accepted RMW and response before a new epoch.
        writes_before = backend_writes;
        fork
            transact(1, 1, 0, 16'h0056, 1, 1, 1);
            begin
                wait (mem_valid && mem_write);
                @(negedge clk); reset_request = 1;
                wait (rsp_valid[1]);
                if (drained) $fatal(1, "Drained before response consumption");
                wait (drained);
                @(negedge clk);
                if (backend_writes != writes_before + 1) $fatal(1, "Reset lost/repeated write");
                reset_request = 0;
            end
        join
        writes_before = backend_writes;
        fork
            transact(0, 1, 4, 16'h1357, 3, 1, 0);
            begin
                wait (busy && backend_write);
                @(negedge clk); reset_request = 1;
                wait (drained);
                @(negedge clk);
                if (backend_writes != writes_before + 1) $fatal(1, "Reset lost issued write");
                reset_request = 0;
            end
        join
        transact(0, 0, 0, 0, 3, 1, 0);

        // Distinct one-hot word addresses must survive all subsequent writes.
        for (i = 1; i < 18; i = i + 1)
            transact(1, 1, 18'b1 << i, 16'h8000 | i[15:0], 3, 1, 0);
        for (i = 1; i < 18; i = i + 1)
            transact(0, 0, 18'b1 << i, 0, 3, 1, 0);
        transact(1, 1, 18'h3fffe, 16'hcdef, 3, 1, 0);
        transact(0, 1, 18'h3fffe, 16'h0042, 1, 1, 0);
        transact(1, 1, 18'h3ffff, 16'hab00, 2, 1, 0);
        transact(0, 0, 18'h3fffe, 0, 3, 1, 0);
        transact(1, 0, 18'h3ffff, 0, 2, 1, 0);
        transact(0, 0, 0, 0, 3, 1, 0);

        host_before = accepted[0]; card_before = accepted[1];
        @(negedge clk);
        host_addr = 0; card_addr = 1;
        host_wdata = 16'h0078; card_wdata = 16'h9a00;
        host_be = 1; card_be = 2;
        req_write = 3; req_write_allowed = 3; req_valid = 3;
        repeat (800) @(negedge clk);
        window_host = accepted[0] - host_before;
        window_card = accepted[1] - card_before;
        $display("CONTENTION ticks=800 host=%0d card=%0d", window_host, window_card);
        fork
            retire_source(0);
            retire_source(1);
        join
        wait (drained);
        @(negedge clk);
        if (DUT_HOST_PRIORITY) begin
            if (window_card != 0 || window_host < 10)
                $fatal(1, "Starvation negative control failed");
            $display("EXPECTED_STARVATION host=%0d card=0", window_host);
        end else begin
            if (window_host < 10 || window_card < 10 ||
                (window_host - window_card > 1) || (window_card - window_host > 1))
                $fatal(1, "Round robin progress/fairness failure");
        end
        transact(0, 0, 0, 0, 3, 1, 0);
        for (i = 0; i < 131072; i = i + 1)
            if (memory[i] !== reference_memory[i]) $fatal(1, "Memory mismatch at %0d", i);
        if (accepted[0] != completed[0] || accepted[1] != completed[1])
            $fatal(1, "Outstanding requests after drain");
        $display("PASS accepted=%0d,%0d completed=%0d,%0d max_accept_to_response_ticks=%0d backend_requests=%0d writes=%0d",
                 accepted[0], accepted[1], completed[0], completed[1],
                 max_latency, backend_requests, backend_writes);
        $finish;
    end

    initial begin
        repeat (5000) @(posedge clk);
        $fatal(1, "Watchdog");
    end
endmodule
