    reg pause_mem = 0;
    integer target_requests = 0, target_completions = 0, reset_commits = 0;
    integer target_stores = 0, restart_stores = 0, uploads = 0;
    integer command_stage = -1, blocked_host_ticks = 0;
    reg injecting = 0, test_active = 0;
    wire target = card_cpu_address == (STAGE == 5 ? 16'hC07D : 16'h0300);
    wire pending_reset = dut.platform.card.card.reset_pending;
    wire reset_command = dut.platform.card.card.reset_command;
    wire reset_commit = dut.platform.card.card.reset_commit;
    wire target_native = native_addr == 24'h540180;
    always @(posedge clk_sys) begin
        if (target && dut.platform.card.card.master_valid[1] && dut.platform.card.card.master_ready[1])
            target_requests = target_requests + 1;
        if (target && cpu_ready) target_completions = target_completions + 1;
        if (pending_reset && (dut.platform.card.card.master_valid[1] ||
            (cpu_ready && !dut.platform.card.card.cpu_memory_wait)))
            $fatal(1, "reset admitted new CPU work");
        if (pending_reset && dut.platform.card.card.req_valid) begin
            if (dut.platform.card.card.req_ready) $fatal(1, "reset admitted new host work");
            blocked_host_ticks = blocked_host_ticks + 1;
        end
        if (reset_commit) begin
            if (!dut.platform.card.card.drained || dut.platform.card.card.cpu_memory_wait ||
                cpu_requests != cpu_responses || backend_count != backend_responses ||
                stores != posted_acks)
                $fatal(1, "reset committed before accepted work drained");
            reset_commits = reset_commits + 1;
        end
        if (injecting && reset_command) begin
            if (!target || target_requests != (STAGE == 5 ? 0 : 1) || target_completions != 0)
                $fatal(1, "reset missed held target cycle");
            case (STAGE)
                0: if (!cpu_wait || card_req) $fatal(1, "reset missed CDC request stage");
                1: if (!target_native || !native_req || native_we || native_ack)
                       $fatal(1, "reset missed native read stage");
                2: if (!target_native || !native_we || !native_ack || target_stores != 0)
                       $fatal(1, "reset missed posted write ACK");
                3: if (target_stores != 1 || cpu_response) $fatal(1, "reset missed committed-write stage");
                4: if (!cpu_response || cpu_response_ready) $fatal(1, "reset missed held CPU response");
                5: if (!capture_valid || cpu_wait) $fatal(1, "reset missed unreleased trap");
                default: $fatal(1, "unknown reset stage");
            endcase
            command_stage = STAGE;
        end
    end
    always @(negedge clk_mem) begin
        if (test_active && {sd_cs, sd_ras, sd_cas, sd_we} == 4'b0100) begin
            if ({sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]} == 23'h540180)
                target_stores = target_stores + 1;
            if ({sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]} == 23'h540182)
                restart_stores = restart_stores + 1;
        end
    end

    task upload(input integer address, input integer value);
        begin
            transact(1, 0, 13, (address >> 17) * 8, 0);
            transact(1, 1, 28, address & 65535, 0);
            transact(1, 0, 16 + ((address >> 16) & 1), value, 0);
            expected[address] = value[7:0];
            uploads = uploads + 1;
        end
    endtask

    task release_reset;
        begin
            wait(capture_valid);
            if (capture_status != 8'h80 || capture_address != 16'hFFFC)
                $fatal(1, "reset vector capture mismatch");
            transact(1, 0, 32, 136, 0);
            transact(1, 0, 12, 0, 0);
        end
    endtask

    initial begin
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1, "missing reset trace");
        traces = $fopen(trace_path, "w");
        if (traces == 0) $fatal(1, "reset trace open failed");
        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        for (i = 0; i < 262144; i = i + 1) expected[i] = 0;
        repeat (3) @(negedge clk_mem);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk_mem); por_n_mem = 1;
        repeat (3) @(negedge clk_sys);
        por_n_sys = 1;
        repeat (5) @(negedge clk_sys);
        upload('h23FFC, 'h00); upload('h23FFD, 'h20);
        upload('h0300, 'h3C); upload('h0301, 'hC3);
        if (WRITING) begin
            upload('h2000, 'hA9); upload('h2001, 'h5A);
            upload('h2002, 'h8D); upload('h2003, 'h00); upload('h2004, 'h03);
        end else begin
            upload('h2000, 'hAD); upload('h2001, STAGE == 5 ? 'h7D : 'h00);
            upload('h2002, STAGE == 5 ? 'hC0 : 'h03);
            upload('h2003, 'h8D); upload('h2004, 'h02); upload('h2005, 'h03);
        end
        transact(1, 0, 13, 0, 0);
        transact(1, 0, 33, 252, 0);
        transact(1, 0, 32, 128, 0);
        test_active = 1;
        release_reset;
        if (STAGE == 0) begin
            // Hold the memory clock before the accepted request crosses domains.
            wait(cpu_valid && target && !cpu_wait);
            pause_mem = 1;
            wait(target_requests == 1);
        end else if (STAGE == 1) begin
            wait(target && target_native && native_req && !native_we && !native_ack);
            pause_mem = 1;
        end else if (STAGE == 2) begin
            wait(target && target_native && native_we && native_ack);
            pause_mem = 1;
        end else if (STAGE == 3) begin
            wait(target_stores == 1);
            pause_mem = 1;
        end else if (STAGE == 4) begin
            wait(target && cpu_response && !cpu_response_ready);
        end else begin
            wait(capture_valid && capture_address == 16'hC07D);
        end
        injecting = 1;
        fork
            begin
                wait(command_stage == STAGE);
                repeat (3) @(negedge clk_sys);
                pause_mem = 0;
            end
            transact(1, STAGE == 3 ? 1 : 0, 32, STAGE == 3 ? 2050 : 128, 0);
        join
        injecting = 0;
        if (STAGE != 3) transact(0, 0, 1, 128, 0);
        wait(reset_commits == 2);
        if (STAGE == 3) begin
            repeat (20) @(negedge clk_sys);
            if (dut.platform.card.card.cpu_running || dut.platform.card.card.start_pending || capture_valid)
                $fatal(1, "word reset restarted CPU");
            transact(1, 0, 32, 128, 0);
        end
        wait(capture_valid);
        if (target_completions != (STAGE == 5 ? 0 : 1) ||
            target_requests != (STAGE == 5 ? 0 : 1) || command_stage != STAGE)
            $fatal(1, "accepted target was lost or duplicated");
        if (WRITING) expected['h300] = 'h5A;
        // The restarted CPU must execute new bytes, never a stale response.
        upload('h2000, 'hA9); upload('h2001, 'hA7); upload('h2002, 'h8D);
        upload('h2003, 'h04); upload('h2004, 'h03);
        upload('h2005, 'h4C); upload('h2006, 'h43); upload('h2007, 'h20);
        release_reset;
        wait(boundary);
        expected['h304] = 'hA7;
        stop_competitors = 1;
        wait(!host_oe && !flp_win && !flp_guard && !floppy_req);
        wait(dut.platform.ownership.drained && dut.platform.adapter.drained &&
             dut.platform.card_crossing.drained && dut.platform.floppy_crossing.drained && !controller.seq_busy);
        repeat (4) @(negedge clk_sys);
        if (cpu_requests != cpu_responses || paced_completions != cpu_completed ||
            accepted != responses || accepted != transaction_count || backend_count != backend_responses ||
            stores != posted_acks || stores != early_acks || stores != uploads + WRITING + 1 ||
            target_stores != WRITING || restart_stores != 1 || capture_count != (STAGE == 5 ? 3 : 2) || capture_valid ||
            reset_commits != (STAGE == 3 ? 3 : 2) || pending_reset ||
            target_requests != (STAGE == 5 ? 0 : 1) || target_completions != (STAGE == 5 ? 0 : 1) ||
            host_services == 0 || floppy_services == 0 || writeback_services == 0 ||
            writeback_services != writeback_reads || !diagnostic_boundary || diagnostic_fault)
            $fatal(1, "reset final accounting mismatch target_stores=%0d", target_stores);
        if (STAGE == 4 && blocked_host_ticks == 0) $fatal(1, "missing pending-reset host backpressure");
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "reset memory mismatch byte=%h", i);
        end
        $display("PASS reset fast=%0d write=%0d stage=%0d CPU=%0d writes=%0d backend=%0d target_complete=%0d commits=%0d",
                 FAST, WRITING, STAGE, cpu_completed, stores, backend_count, target_completions, reset_commits);
        $fclose(traces);
        $finish;
    end
