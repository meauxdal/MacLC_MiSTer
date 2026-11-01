`timescale 1ns/1ps
module tb_card_candidate;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0;
    reg req_valid = 0, req_word = 0, req_write = 0, rsp_ready = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error, fault, boundary;
    wire [15:0] rsp_rdata, cpu_address, capture_address;
    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    reg mem_ready = 0, mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    card_candidate dut (.*);
    reg [15:0] memory [0:131071];
    reg [7:0] expected [0:262143];
    reg backend_busy = 0, backend_write;
    reg [16:0] backend_addr;
    reg [15:0] backend_data;
    integer ticks = 0, delay_scale = 1, countdown = 0, backend_count = 0;
    integer accepted = 0, responses = 0, stores = 0;
    integer stimulus, traces, status, writing, word_access, offset, value, gap;
    integer transaction_count = 0, i, last_capture = 0;
    integer capture_checks = 0, nonreport_checked = 0, saved_backend, saved_stores;
    reg [1023:0] stimulus_path, expected_path, trace_path;

    always @(negedge clk) begin
        mem_ready = por_n && !backend_busy && !mem_rsp_valid && (ticks % 5 != 0);
    end
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 2000000) $fatal(1, "system watchdog");
        if (por_n && fault) $fatal(1, "candidate fault CPU=%h capture=%h", cpu_address, capture_address);
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
        if (req_valid && req_ready) accepted <= accepted + 1;
        if (rsp_valid && rsp_ready) responses <= responses + 1;
        if (capture_count != last_capture) begin
            if (!capture_valid) $fatal(1, "capture disappeared before observation");
            $fdisplay(traces, "%02x %04x %02x", capture_status, capture_address, capture_data);
            last_capture = capture_count;
        end
    end

    task transact;
        input integer write_arg, word_arg, offset_arg, value_arg, gap_arg;
        integer n;
        begin
            repeat (gap_arg) @(negedge clk);
            req_valid = 1;
            req_write = write_arg != 0;
            req_word = word_arg != 0;
            req_offset = offset_arg[5:0];
            req_wdata = value_arg[15:0];
            @(posedge clk);
            while (!req_ready) @(posedge clk);
            @(negedge clk);
            req_valid = 0;
            while (!rsp_valid) @(negedge clk);
            if (rsp_error) $fatal(1, "host error offset %h", req_offset);
            if (write_arg == 0 && rsp_rdata !== value_arg[15:0])
                $fatal(1, "host read transaction=%0d offset=%h expected=%h actual=%h CPU=%h capture=%h",
                       transaction_count, req_offset, value_arg[15:0], rsp_rdata, cpu_address, capture_status);
            for (n = 0; n < transaction_count % 4; n = n + 1) begin
                @(negedge clk);
                if (!rsp_valid || (write_arg == 0 && rsp_rdata !== value_arg[15:0]))
                    $fatal(1, "host response unstable");
            end
            rsp_ready = 1;
            @(negedge clk);
            rsp_ready = 0;
            transaction_count = transaction_count + 1;
        end
    endtask

    initial begin
        if (!$value$plusargs("stimulus=%s", stimulus_path)) $fatal(1, "missing stimulus");
        if (!$value$plusargs("expected=%s", expected_path)) $fatal(1, "missing expected");
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1, "missing trace");
        if (!$value$plusargs("delay=%d", delay_scale)) delay_scale = 1;
        if (!$value$plusargs("capture_checks=%d", capture_checks)) capture_checks = 0;
        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        $readmemh(expected_path, expected);
        stimulus = $fopen(stimulus_path, "r");
        traces = $fopen(trace_path, "w");
        if (stimulus == 0 || traces == 0) $fatal(1, "file open failed");
        repeat (3) @(negedge clk);
        por_n = 1;
        @(negedge clk);
        while (!$feof(stimulus)) begin
            status = $fscanf(stimulus, "%d %d %d %d %d\n", writing, word_access, offset, value, gap);
            if (status == 5) begin
                transact(writing, word_access, offset, value, gap);
                if (capture_checks != 0 && nonreport_checked == 0 && capture_valid && capture_status == 8'h0A) begin
                    saved_backend = backend_count;
                    saved_stores = stores;
                    transact(1, 0, 13, 3, 0);
                    repeat (30) @(negedge clk);
                    if (!capture_valid || capture_status != 8'h0A ||
                        backend_count != saved_backend || stores != saved_stores)
                        $fatal(1, "control change bypassed pending capture");
                    transact(1, 0, 32, 152, 0);
                    transact(0, 1, 4, 1024, 0);
                    repeat (30) @(negedge clk);
                    if (!capture_valid || capture_status != 8'h0A || stores != saved_stores)
                        $fatal(1, "live report mode changed release policy");
                    transact(1, 0, 32, 136, 0);
                    transact(1, 0, 13, 0, 0);
                    nonreport_checked = 1;
                end
                if (capture_checks != 0 && capture_valid && capture_status == 8'h0B) begin
                    saved_stores = stores;
                    transact(1, 0, 32, 136, 0);
                    transact(0, 1, 4, 1024, 0);
                    repeat (600) @(negedge clk);
                    if (!capture_valid || capture_status != 8'hE0 || capture_address != 16'hC07D ||
                        stores != saved_stores + 1)
                        $fatal(1, "captured report-mode release did not commit once");
                    saved_stores = stores;
                    transact(1, 0, 32, 128, 0);
                    repeat (600) @(negedge clk);
                    if (!capture_valid || capture_status != 8'h80 || capture_address != 16'hFFFC ||
                        stores != saved_stores)
                        $fatal(1, "pending report reset did not preserve memory");
                    $display("PASS capture controls: sticky suspension, snapshotted release, single commit, reset cancellation");
                    $finish;
                end
            end
            else if (status != -1) $fatal(1, "bad stimulus");
        end
        repeat (600) @(negedge clk);
        if (!boundary || cpu_address != 16'h202F) $fatal(1, "wrong boundary %h", cpu_address);
        if (capture_valid || capture_count != 39) $fatal(1, "wrong captures %0d", capture_count);
        if (accepted != responses || accepted != transaction_count)
            $fatal(1, "host acceptance/response mismatch");
        if (backend_busy || mem_rsp_valid || dut.cpu_memory_wait) $fatal(1, "backend not drained");
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "memory mismatch byte %h", i);
        end
        if (dut.processor.cpu.reg_s !== 8'hFD) $fatal(1, "CPU stack not restored");
        $display("PASS host=%0d backend=%0d stores=%0d captures=%0d cpu_cycles=%0d ticks=%0d",
                 transaction_count, backend_count, stores, capture_count, cpu_completed, ticks);
        $fclose(stimulus);
        $fclose(traces);
        $finish;
    end
endmodule
