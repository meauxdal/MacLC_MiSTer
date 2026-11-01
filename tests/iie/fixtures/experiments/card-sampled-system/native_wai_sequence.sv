    integer idle_requests, idle_completions, idle_samples, uploads = 0;
    integer reset_captures = 0;
    wire waiting = dut.platform.card.card.processor.waiting;
    always @(posedge clk_sys) begin
        if (waiting && (cpu_valid || cpu_ready || dut.platform.card.card.master_valid[1]))
            $fatal(1, "native WAI issued a CPU transaction");
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

    task hold_wai;
        begin
            wait(waiting);
            @(negedge clk_sys);
            idle_requests = cpu_requests;
            idle_completions = cpu_completed;
            idle_samples = 0;
            while (idle_samples < 8) begin
                @(negedge clk_sys);
                if (pace_due) idle_samples = idle_samples + 1;
                if (!waiting || cpu_requests != idle_requests || cpu_completed != idle_completions)
                    $fatal(1, "native WAI did not hold idle");
            end
        end
    endtask

    task release_reset;
        begin
            wait(capture_valid);
            if (capture_status != 8'h80 || capture_address != 16'hFFFC)
                $fatal(1, "native WAI reset capture mismatch");
            reset_captures = reset_captures + 1;
            transact(0, 0, 1, 128, 0);
            transact(0, 1, 4, 65532, 0);
            transact(1, 0, 32, 136, 0);
            transact(1, 0, 12, 0, 0);
        end
    endtask

    initial begin
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1, "missing native WAI trace");
        traces = $fopen(trace_path, "w");
        if (traces == 0) $fatal(1, "native WAI trace open failed");
        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        for (i = 0; i < 262144; i = i + 1) expected[i] = 0;
        repeat (3) @(negedge clk_mem);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk_mem); por_n_mem = 1;
        repeat (3) @(negedge clk_sys);
        por_n_sys = 1;
        repeat (5) @(negedge clk_sys);

        // Upload through PDS, including context-bank reset and IRQ vectors.
        upload('h23FFC, 'h00); upload('h23FFD, 'h20);
        upload('h23FFE, 'h00); upload('h23FFF, 'h22);
        upload('h2000, MASKED ? 'h78 : 'h58);
        upload('h2001, 'hCB); upload('h2002, 'hA9); upload('h2003, 'h42);
        upload('h2004, 'h8D); upload('h2005, 'h00); upload('h2006, 'h02);
        upload('h2007, 'h4C); upload('h2008, 'h43); upload('h2009, 'h20);
        upload('h2200, 'hEE); upload('h2201, 'h01); upload('h2202, 'h02); upload('h2203, 'h40);
        transact(1, 0, 13, 0, 0);
        transact(1, 0, 33, 252, 0);
        transact(1, 0, 32, 128, 0);
        release_reset;
        hold_wai;

        // Host-only reset preserves an idle WAI CPU and its backend.
        host_reset = 1;
        repeat (20) @(negedge clk_sys);
        host_reset = 0;
        hold_wai;
        upload('h3000, 'hA5);
        transact(1, 1, 28, 'h3000, 0);
        transact(0, 0, 16, 'hA5, 0);
        if (!waiting || cpu_requests != idle_requests || cpu_completed != idle_completions)
            $fatal(1, "host stream service advanced WAI CPU");

        // A card restart is permitted only after its accepted work drains.
        wait(dut.platform.card.card.drained && !dut.platform.card.card.cpu_memory_wait);
        transact(1, 0, 32, 128, 0);
        wait(!waiting);
        release_reset;
        hold_wai;
        transact(1, 0, 32, 168, 0);
        wait(!waiting);
        if (!MASKED) wait(irqs == 1);
        transact(1, 0, 32, 136, 0);
        wait(boundary);
        if (!MASKED) begin
            expected['h201] = 1;
            expected['h1FB] = 'h20;
            expected['h1FC] = 'h02;
            expected['h1FD] = 'h20;
        end
        expected['h200] = 'h42;
        stop_competitors = 1;
        wait(!host_oe && !flp_win && !flp_guard && !floppy_req);
        wait(dut.platform.ownership.drained && dut.platform.adapter.drained &&
             dut.platform.card_crossing.drained && dut.platform.floppy_crossing.drained && !controller.seq_busy);
        repeat (4) @(negedge clk_sys);
        if (cpu_requests != cpu_responses || paced_completions != cpu_completed ||
            accepted != responses || accepted != transaction_count ||
            backend_count != backend_responses || stores != posted_acks || stores != early_acks ||
            stores != uploads + (MASKED ? 1 : 5) || writeback_services != writeback_reads ||
            host_services == 0 || floppy_services == 0 || writeback_services == 0 || refreshes <= 8 ||
            irqs != (MASKED ? 0 : 1) || rtis != irqs || nmis != 0 || opcodes != 0 ||
            capture_count != 2 || reset_captures != 2 || capture_valid ||
            dut.platform.card.card.processor.cpu.reg_s !== 8'hFD || !diagnostic_boundary || diagnostic_fault)
            $fatal(1, "native WAI count/drain mismatch stores=%0d uploads=%0d IRQ=%0d RTI=%0d", stores, uploads, irqs, rtis);
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "native WAI memory mismatch byte=%h", i);
        end
        $display("PASS native WAI fast=%0d masked=%0d PDS=%0d CPU=%0d writes=%0d captures=%0d IRQ=%0d RTI=%0d min_gap=%0d",
                 FAST, MASKED, transaction_count, cpu_completed, stores, capture_count, irqs, rtis, min_gap);
        $display("native WAI contention host=%0d window=%0d mailbox=%0d refresh=%0d backend=%0d max_latency=%0d",
                 host_services, floppy_services, writeback_services, refreshes, backend_count, max_backend_latency);
        $fclose(traces);
        $finish;
    end
