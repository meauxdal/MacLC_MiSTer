    integer service_writes = 0, ram_writes = 0, service_pc = -1, service_id = -1;
    reg [7:0] saved_a, saved_x, saved_y, saved_s, saved_p;
    integer instructions, switch_services = 0;
    integer cx_reads = 0, slot3_reads = 0, cfff_reads = 0, row, column, text_address;
    reg [7:0] text_expected [0:1023];
    reg [1023:0] image_path;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.opcode02_complete) begin
            service_pc = 32'(card_cpu_address);
            service_id = 32'(expected['h20000 + 32'(card_cpu_address) - 'hC000 + 1]);
            saved_a = dut.platform.card.card.processor.cpu.reg_a;
            saved_x = dut.platform.card.card.processor.cpu.reg_x;
            saved_y = dut.platform.card.card.processor.cpu.reg_y;
            saved_s = dut.platform.card.card.processor.cpu.reg_s;
            saved_p = dut.platform.card.card.processor.cpu.reg_p;
        end
        if (cpu_ready) begin
            if (!dut.platform.card.card.cpu_write && card_cpu_address >= 16'hC100 && card_cpu_address < 16'hCFFF) begin
                if (dut.platform.card.card.slot3_read) begin
                    if (card_cpu_address != 16'hC307 || dut.platform.card.card.cpu_rdata != 8'hEA)
                        $fatal(1, "monitor external slot3 probe mismatch");
                    slot3_reads = slot3_reads + 1;
                end else if (!dut.platform.card.card.internal_cx)
                    $fatal(1, "monitor unselected Cx read");
                cx_reads = cx_reads + 1;
            end
            if (!dut.platform.card.card.cpu_write && card_cpu_address == 16'hCFFF)
                cfff_reads = cfff_reads + 1;
            if (dut.platform.card.card.vector_pull && card_cpu_address == 16'hFFFA &&
                dut.platform.card.card.cpu_rdata != 0) $fatal(1, "normal NMI vector mismatch");
            if (dut.platform.card.card.cpu_sync) begin
                $fdisplay(instructions, "%04x %02x A=%02x X=%02x Y=%02x S=%02x", card_cpu_address,
                          dut.platform.card.card.cpu_rdata, dut.platform.card.card.processor.cpu.reg_a,
                          dut.platform.card.card.processor.cpu.reg_x, dut.platform.card.card.processor.cpu.reg_y,
                          dut.platform.card.card.processor.cpu.reg_s);
            end
            if (dut.platform.card.card.cpu_write && dut.platform.card.card.service_register)
                service_writes = service_writes + 1;
            if (dut.platform.card.card.cpu_write && !dut.platform.card.card.io_space) begin
                if (dut.platform.card.card.physical >= 'h20000) $fatal(1, "monitor wrote firmware backing");
                expected[dut.platform.card.card.physical] = dut.platform.card.card.cpu_wdata;
                ram_writes = ram_writes + 1;
            end
        end
    end

    initial begin
        if (!$value$plusargs("image=%s", image_path) || !$value$plusargs("trace=%s", trace_path) ||
            !$value$plusargs("instructions=%s", stimulus_path)) $fatal(1, "missing monitor inputs");
        traces = $fopen(trace_path, "w");
        instructions = $fopen(stimulus_path, "w");
        if (traces == 0 || instructions == 0) $fatal(1, "monitor trace open failed");
        $readmemh(image_path, expected);
        for (i = 0; i < 131072; i = i + 1) memory[i] = {expected[i*2+1], expected[i*2]};
        repeat (3) @(negedge clk_mem);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk_mem); por_n_mem = 1;
        repeat (3) @(negedge clk_sys);
        por_n_sys = 1;
        repeat (5) @(negedge clk_sys);
        transact(1, 0, 33, 252, 0);
        transact(1, 0, 32, 128, 0);
        wait(capture_valid);
        if (capture_address != 16'hFFFC || capture_status != 8'h80) $fatal(1, "monitor reset capture");
        transact(0, 1, 4, 65532, 0);
        transact(1, 0, 13, 3, 0);
        transact(1, 0, 32, 136, 0);
        transact(1, 0, 12, 0, 0);
        wait(capture_valid);
        while (capture_address != 16'hC07D) begin
            if (capture_status != 8'h08 || !dut.platform.card.card.display_switch)
                $fatal(1, "unsupported monitor host service address=%h status=%h", capture_address, capture_status);
            case (switch_services)
                0: if (capture_address != 16'hC00E) $fatal(1, "monitor switch order");
                1: if (capture_address != 16'hC001) $fatal(1, "monitor switch order");
                2: if (capture_address != 16'hC055) $fatal(1, "monitor switch order");
                3: if (capture_address != 16'hC054) $fatal(1, "monitor switch order");
                4: if (capture_address != 16'hC000) $fatal(1, "monitor switch order");
                default: $fatal(1, "extra monitor switch");
            endcase
            transact(0, 1, 4, 32'(capture_address), 0);
            transact(1, 0, 12, 0, 0);
            switch_services = switch_services + 1;
            wait(!capture_valid);
            wait(capture_valid);
        end
        $display("MONITOR report PC=%h status=%h data=%h opcode_PC=%h service=%h CPU=%0d",
                 capture_address, capture_status, capture_data, service_pc, service_id, cpu_completed);
        if (capture_address != 16'hC07D || capture_status != 8'hE0 || capture_data != 8'(service_id) ||
            service_writes != 5 || nmis != 1 || irqs != 0 || opcodes != 1 ||
            service_pc != 32'hFBDD || service_id != 1 || switch_services != 5)
            $fatal(1, "normal monitor service contract mismatch");
        if (dut.platform.card.card.service_regs[0] != saved_a ||
            dut.platform.card.card.service_regs[1] != saved_x ||
            dut.platform.card.card.service_regs[2] != saved_y ||
            dut.platform.card.card.service_regs[4] != saved_s - 8'd3)
            $fatal(1, "monitor receiver saved registers incorrectly");
        transact(0, 0, 12, service_id, 0);
        transact(1, 0, 12, 0, 0);
        wait(dut.platform.card.card.cpu_valid && dut.platform.card.card.cpu_sync && card_cpu_address == 16'hFBDF);
        if (card_cpu_address != 16'(service_pc + 2) || rtis != 1 ||
            dut.platform.card.card.processor.cpu.reg_a != saved_a ||
            dut.platform.card.card.processor.cpu.reg_x != saved_x ||
            dut.platform.card.card.processor.cpu.reg_y != saved_y ||
            dut.platform.card.card.processor.cpu.reg_s != saved_s ||
            dut.platform.card.card.processor.cpu.reg_p != saved_p)
            $fatal(1, "monitor service did not restore interrupted execution");
        wait(boundary);
        if (card_cpu_address != 16'hFB63 || opcodes != 1 || rtis != 1 ||
            expected['h20000 + 'hFB63 - 'hC000] != 8'h02 ||
            expected['h20000 + 'hFB64 - 'hC000] != 8'h04)
            $fatal(1, "monitor next service boundary mismatch");
        for (i = 0; i < 1024; i = i + 1) text_expected[i] = 0;
        for (row = 0; row < 24; row = row + 1)
            for (column = 0; column < 40; column = column + 1) begin
                text_address = (row % 8) * 128 + (row / 8) * 40 + column;
                text_expected[text_address] = 8'hA0;
            end
        stop_competitors = 1;
        wait(!host_oe && !flp_win && !flp_guard && !floppy_req);
        wait(dut.platform.ownership.drained && dut.platform.adapter.drained &&
             dut.platform.card_crossing.drained && dut.platform.floppy_crossing.drained && !controller.seq_busy);
        repeat (4) @(negedge clk_sys);
        if (cpu_requests != cpu_responses || paced_completions != cpu_completed || accepted != responses ||
            accepted != transaction_count || backend_count != backend_responses || stores != ram_writes ||
            stores != posted_acks || stores != early_acks || capture_count != switch_services + 2 || capture_valid ||
            writeback_services != writeback_reads || host_services == 0 || floppy_services == 0 ||
            writeback_services == 0 || !diagnostic_boundary || diagnostic_fault)
            $fatal(1, "monitor endpoint accounting mismatch");
        for (i = 0; i < 262144; i = i + 1) begin
            if ((i % 2 == 0 && memory[i / 2][7:0] !== expected[i]) ||
                (i % 2 == 1 && memory[i / 2][15:8] !== expected[i]))
                $fatal(1, "monitor memory transport mismatch byte=%h", i);
        end
        for (i = 0; i < 1024; i = i + 1) begin
            if (text_expected[i] == 8'hA0 &&
                (expected['h400 + i] != 8'hA0 || expected['h10400 + i] != 0))
                $fatal(1, "monitor text clear mismatch offset=%h", i);
        end
        if (cx_reads == 0 || slot3_reads != 1 || cfff_reads != 1 || dut.platform.card.card.slot3_rom)
            $fatal(1, "monitor Cx routing coverage mismatch Cx=%0d slot3=%0d CFFF=%0d slot3_rom=%0d",
                   cx_reads, slot3_reads, cfff_reads, dut.platform.card.card.slot3_rom);
        $display("MAPPING Cx_reads=%0d slot3_reads=%0d CFFF_reads=%0d text_bytes=960 aux_bytes=960",
                 cx_reads, slot3_reads, cfff_reads);
        if (expected['h32] != 'hFF || expected['h48] != 0 ||
            expected['h36] != 'hF0 || expected['h37] != 'hFD ||
            expected['h38] != 'h1B || expected['h39] != 'hFD)
            $fatal(1, "monitor initial state mismatch");
        $display("PASS monitor fast=%0d next_PC=%h service=%0d CPU=%0d writes=%0d backend=%0d min_gap=%0d",
                 FAST, card_cpu_address, service_id, cpu_completed, stores, backend_count, min_gap);
        $fclose(traces);
        $fclose(instructions);
        $finish;
    end
