    initial begin
        if (!$value$plusargs("image=%s", image_path) || !$value$plusargs("trace=%s", trace_path) ||
            !$value$plusargs("instructions=%s", stimulus_path)) $fatal(1, "missing switch inputs");
        traces = $fopen(trace_path, "w");
        instructions = $fopen(stimulus_path, "w");
        if (!traces || !instructions) $fatal(1, "trace open failed");
        $readmemh(image_path, expected);
        for (i = 0; i < 131072; i = i + 1) memory[i] = {expected[i*2+1], expected[i*2]};
        repeat (3) @(negedge clk_mem);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk_mem); por_n_mem = 1;
        repeat (3) @(negedge clk_sys); por_n_sys = 1;
        repeat (5) @(negedge clk_sys);
        transact(1, 0, 33, 252, 0);
        transact(1, 0, 32, 128, 0);
        wait(capture_valid);
        if (capture_address != 16'hFFFC || capture_status != 8'h80) $fatal(1, "reset capture");
        transact(0, 1, 4, 65532, 0);
        transact(1, 0, 13, 3, 0);
        transact(1, 0, 32, 136, 0);
        transact(1, 0, 12, 0, 0);
        wait(capture_valid);
        if (capture_address != 16'hC00E || capture_status != 8'hE0) $fatal(1, "first switch capture");
        bridge_active = 1;
        $display("READY"); $fflush();
        for (bridge_index = 1; bridge_index <= 10; bridge_index = bridge_index + 1) begin
            if (bridge_index == 5) wait(capture_valid && capture_address == 16'hC001);
            bridge_fields = $fscanf(32'h80000000, "%d %d %d %d %d",
                bridge_sequence, bridge_write, bridge_width, bridge_offset, bridge_value);
            if (bridge_fields != 5 || bridge_sequence != bridge_index ||
                (bridge_write != 0 && bridge_write != 1) ||
                (bridge_width != 8 && bridge_width != 16)) $fatal(1, "invalid bridge request");
            transact(bridge_write, bridge_width == 16, bridge_offset, bridge_value, 0);
            $display("REPLY %0d %0d", bridge_sequence, bridge_reply); $fflush();
        end
        bridge_active = 0;
        wait(boundary);
        if (capture_address != 16'hC055 || capture_status != 8'hE0 || capture_count != 4 ||
            opcodes != 0 || nmis != 0 || rtis != 0 || service_writes != 0 ||
            dut.platform.card.card.mode_altchar || !dut.platform.card.card.mode_store80 ||
            dut.platform.card.card.control != 8'h01)
            $fatal(1, "next switch boundary");
        stop_competitors = 1;
        wait(!host_oe && !flp_win && !flp_guard && !floppy_req);
        wait(dut.platform.ownership.drained && dut.platform.adapter.drained &&
             dut.platform.card_crossing.drained && dut.platform.floppy_crossing.drained && !controller.seq_busy);
        repeat (4) @(negedge clk_sys);
        if (cpu_requests != cpu_responses || paced_completions != cpu_completed || accepted != responses ||
            accepted != transaction_count || backend_count != backend_responses || stores != ram_writes ||
            stores != posted_acks || stores != early_acks || !capture_valid ||
            writeback_services != writeback_reads || host_services == 0 || floppy_services == 0 ||
            writeback_services == 0 || !diagnostic_boundary || diagnostic_fault)
            $fatal(1, "switch endpoint accounting mismatch");
        for (i = 0; i < 262144; i = i + 1)
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i])) $fatal(1, "memory transport mismatch");
        $display("PASS switch next=%h CPU=%0d writes=%0d backend=%0d", capture_address, cpu_completed, stores, backend_count);
        $fclose(traces); $fclose(instructions);
        $finish;
    end
