`timescale 1ns/1ps
module tb_pds_candidate;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0;
    reg host_reset = 0;
    reg [31:0] pds_address = 0;
    reg [2:0] pds_fc = 3'b001;
    reg pds_as_n = 1, pds_uds_n = 1, pds_lds_n = 1, pds_rw = 1;
    reg [15:0] pds_write_data = 0;
    wire claim, dtack_n, error, fault, boundary;
    wire [15:0] pds_read_data, card_cpu_address, capture_address;
    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    reg mem_ready = 0, mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    card_pds_candidate dut (.*);
    reg [15:0] memory [0:131071];
    reg [7:0] expected [0:262143];
    reg backend_busy = 0, backend_write;
    reg [16:0] backend_addr;
    reg [15:0] backend_data;
    integer ticks = 0, delay_scale = 1, countdown = 0, backend_count = 0;
    integer accepted = 0, responses = 0, stores = 0;
    integer stimulus, traces, status, writing, word_access, offset, value, gap;
    integer transaction_count = 0, i, last_capture = 0;
    reg [1023:0] stimulus_path, expected_path, trace_path;
    reg [32:0] held_backend;

    always @(negedge clk) begin
        mem_ready = por_n && !backend_busy && !mem_rsp_valid && (ticks % 5 != 0);
    end
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 2000000) $fatal(1, "system watchdog");
        if (por_n && fault) $fatal(1, "candidate fault CPU=%h capture=%h", card_cpu_address, capture_address);
        if (mem_valid && mem_ready) begin
            if (backend_busy || mem_rsp_valid) $fatal(1, "overlapping backend operation");
            backend_busy <= 1;
            backend_write <= mem_write;
            backend_addr <= mem_addr;
            backend_data <= mem_wdata;
            countdown <= 1 + delay_scale * (backend_count % 8);
            backend_count <= backend_count + 1;
        end
        if (backend_busy) begin
            if (countdown == 0) begin
                if (backend_write) begin
                    memory[backend_addr] <= backend_data;
                    stores <= stores + 1;
                    mem_rdata <= 0;
                end else mem_rdata <= memory[backend_addr];
                mem_rsp_valid <= 1;
                backend_busy <= 0;
            end else countdown <= countdown - 1;
        end
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (dut.req_valid && dut.req_ready) accepted <= accepted + 1;
        if (dut.rsp_valid && dut.rsp_ready) responses <= responses + 1;
        if (capture_count != last_capture) begin
            if (!capture_valid) $fatal(1, "capture disappeared before observation");
            $fdisplay(traces, "%02x %04x %02x", capture_status, capture_address, capture_data);
            last_capture = capture_count;
        end
    end

    task transact;
        input integer write_arg, word_arg, offset_arg, value_arg, gap_arg;
        integer n, before_count;
        reg [31:0] base;
        reg [15:0] expected_data;
        begin
            repeat (gap_arg) @(negedge clk);
            case (transaction_count % 3)
                0: base = 32'h80000000;
                1: base = 32'h80E00000;
                2: base = 32'h00E00000;
            endcase
            if (word_arg && offset_arg[0]) $fatal(1, "unaligned word stimulus");
            before_count = accepted;
            pds_address = base + (offset_arg & 32'hFFFFFFFE);
            pds_rw = write_arg == 0;
            pds_fc = transaction_count[0] ? 3'b101 : 3'b001;
            pds_write_data = word_arg ? value_arg[15:0] :
                             offset_arg[0] ? {8'hD3, value_arg[7:0]} : {value_arg[7:0], 8'hD3};
            pds_as_n = 0;
            #1;
            if (!claim || !dtack_n) $fatal(1, "early claim");
            repeat (2) @(negedge clk);
            if (accepted != before_count) $fatal(1, "request without strobes");
            pds_uds_n = !word_arg && offset_arg[0];
            pds_lds_n = !word_arg && !offset_arg[0];
            while (dtack_n) begin
                @(negedge clk);
                if (!claim || error) $fatal(1, "PDS error transaction %0d", transaction_count);
            end
            expected_data = word_arg ? value_arg[15:0] :
                            offset_arg[0] ? {8'hFF, value_arg[7:0]} : {value_arg[7:0], 8'hFF};
            if (!write_arg && pds_read_data !== expected_data)
                $fatal(1, "PDS read transaction=%0d offset=%h expected=%h actual=%h CPU=%h capture=%h",
                       transaction_count, offset_arg, expected_data, pds_read_data, card_cpu_address, capture_status);
            for (n = 0; n < 3 + transaction_count % 5; n = n + 1) begin
                @(negedge clk);
                if (dtack_n || !claim || accepted != before_count + 1 ||
                    (!write_arg && pds_read_data !== expected_data))
                    $fatal(1, "held AS duplicates or changes transaction");
            end
            pds_as_n = 1;
            pds_uds_n = 1;
            pds_lds_n = 1;
            #1;
            if (claim || !dtack_n) $fatal(1, "AS release");
            @(negedge clk);
            transaction_count = transaction_count + 1;
        end
    endtask

    task unclaimed(input [31:0] a, input [2:0] fc);
        integer before_count;
        begin
            before_count = accepted;
            pds_address = a; pds_fc = fc; pds_as_n = 0;
            pds_uds_n = 0; pds_lds_n = 0; pds_rw = 1;
            repeat (5) begin
                #1;
                if (claim || !dtack_n || error) $fatal(1, "nonclaimed address %h FC %h", a, fc);
                @(negedge clk);
            end
            if (accepted != before_count) $fatal(1, "nonclaimed access reached registers");
            pds_as_n = 1; pds_uds_n = 1; pds_lds_n = 1;
            @(negedge clk);
        end
    endtask

    task unsupported;
        integer before_count;
        begin
            before_count = accepted;
            pds_address = 32'h00E00022; pds_fc = 3'b001;
            pds_as_n = 0; pds_uds_n = 0; pds_lds_n = 1; pds_rw = 1;
            while (!error) @(negedge clk);
            repeat (5) begin
                if (!claim || !dtack_n || accepted != before_count + 1)
                    $fatal(1, "unsupported register bus policy");
                @(negedge clk);
            end
            pds_as_n = 1; pds_uds_n = 1;
            @(negedge clk);
        end
    endtask

    task abort_accepted_read;
        integer before_count;
        begin
            before_count = accepted;
            pds_address = 32'h80000010; pds_fc = 3'b101;
            pds_as_n = 0; pds_uds_n = 0; pds_lds_n = 0; pds_rw = 1;
            while (accepted == before_count) @(negedge clk);
            host_reset = 1;
            repeat (5) begin
                #1;
                if (claim || !dtack_n) $fatal(1, "host reset acknowledged aborted access");
                @(negedge clk);
            end
            pds_as_n = 1; pds_uds_n = 1; pds_lds_n = 1;
            host_reset = 0;
            while (dut.pds.state != 3'd1) @(negedge clk);
            if (accepted != before_count + 1 || responses != accepted || dut.card.host_index != 1)
                $fatal(1, "accepted stream read failed to drain across host reset");
            if (backend_busy || mem_rsp_valid) $fatal(1, "aborted backend not drained");
        end
    endtask

    initial begin
        if (!$value$plusargs("stimulus=%s", stimulus_path)) $fatal(1, "missing stimulus");
        if (!$value$plusargs("expected=%s", expected_path)) $fatal(1, "missing expected");
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1, "missing trace");
        if (!$value$plusargs("delay=%d", delay_scale)) delay_scale = 1;
        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        $readmemh(expected_path, expected);
        stimulus = $fopen(stimulus_path, "r");
        traces = $fopen(trace_path, "w");
        if (!stimulus || !traces) $fatal(1, "file open failed");
        repeat (3) @(negedge clk);
        por_n = 1;
        @(negedge clk);
        unclaimed(32'h00D00000, 3'b001);
        unclaimed(32'h80000024, 3'b001);
        unclaimed(32'h80E00025, 3'b001);
        unclaimed(32'h00E00001, 3'b001);
        unclaimed(32'h00E00000, 3'b111);
        unsupported;
        abort_accepted_read;
        while (!$feof(stimulus)) begin
            status = $fscanf(stimulus, "%d %d %d %d %d\n", writing, word_access, offset, value, gap);
            if (status == 5) transact(writing, word_access, offset, value, gap);
            else if (status != -1) $fatal(1, "bad stimulus");
        end
        repeat (600) @(negedge clk);
        if (!boundary || card_cpu_address != 16'h202F) $fatal(1, "wrong boundary %h", card_cpu_address);
        if (capture_valid || capture_count != 39) $fatal(1, "wrong captures %0d", capture_count);
        if (accepted != responses || accepted != transaction_count + 2)
            $fatal(1, "host acceptance/response mismatch");
        if (backend_busy || mem_rsp_valid || dut.card.cpu_memory_wait) $fatal(1, "backend not drained");
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "memory mismatch byte %h", i);
        end
        if (dut.card.processor.cpu.reg_s !== 8'hFD) $fatal(1, "CPU stack not restored");
        $display("PASS PDS=%0d backend=%0d stores=%0d captures=%0d cpu_cycles=%0d ticks=%0d plus 5 unclaimed, 1 unsupported, 1 reset-drained read",
                 transaction_count, backend_count, stores, capture_count, cpu_completed, ticks);
        $fclose(stimulus);
        $fclose(traces);
        $finish;
    end
endmodule
