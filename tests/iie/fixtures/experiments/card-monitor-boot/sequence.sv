        while (!boundary) begin
            wait(capture_valid || boundary);
            @(negedge clk_sys);
            if (capture_valid && !boundary) begin
                $display("CONTINUE address=%h status=%h data=%h PC=%h service=%0d", capture_address,
                         capture_status, capture_data, service_pc, service_id);
                if (capture_address == 16'hC07D) begin
                    if (capture_status != 8'hE0 || capture_data != 8'(service_id) ||
                        service_id != 4 || service_pc != 'hFB63 || opcodes != 2 ||
                        nmis != opcodes || service_writes != 5 * opcodes)
                        $fatal(1, "continuation service mismatch");
                    if (saved_y !== 0) $fatal(1, "unexpected service4 Y");
                    copy_count = preserve_y ? 256 : 9;
                    for (i = 0; i < 256; i = i + 1) begin
                        source_address = ('hFF09 + i) & 'hFFFF;
                        if (source_address >= 'hFFFA)
                            banner_source[i] = expected['h27FFA + source_address - 'hFFFA];
                        else if (source_address >= 'hC000)
                            banner_source[i] = expected['h20000 + source_address - 'hC000];
                        else banner_source[i] = expected[source_address];
                    end
                    // Inject the original host handler's saved-Y result.
                    if (!preserve_y) dut.platform.card.card.service_regs[2] = 9;
                    transact(0, 0, 12, service_id, 0);
                end else begin
                    if (capture_status != 8'h08 || !dut.platform.card.card.display_switch)
                        $fatal(1, "unsupported continuation capture");
                    transact(0, 1, 4, 32'(capture_address), 0);
                    switch_services = switch_services + 1;
                end
                transact(1, 0, 12, 0, 0);
                wait(!capture_valid);
            end
        end
        if (service_pc != 'hFAB4 || service_id != 2 || opcodes != 3 || rtis != 2 ||
            nmis != 3 || service_writes != 15 || capture_status != 8'hE0 || switch_services != 5)
            $fatal(1, "boot service boundary mismatch");
        for (i = preserve_y ? 0 : 1; i < (preserve_y ? 256 : 10); i = i + 1)
            if (expected['h40E + i] !== banner_source[i])
                $fatal(1, "original banner mismatch");
        for (i = 1; i <= 5; i = i + 1)
            if (expected['h3EF + i] !== expected['h20000 + 'h3AFC + i])
                $fatal(1, "original reset vector copy mismatch");
        for (row = 0; row < 24; row = row + 1)
            for (column = 0; column < 40; column = column + 1) begin
                text_address = (row % 8) * 128 + (row / 8) * 40 + column;
                if (expected['h400 + text_address] !==
                    (text_address >= (preserve_y ? 'h0E : 'h0F) && text_address <= (preserve_y ? 'h10D : 'h17) ?
                     banner_source[text_address - 'h0E] : 8'hA0) ||
                    expected['h10400 + text_address] !== 0)
                    $fatal(1, "original banner page mismatch");
            end
        $display("COPY bytes=%0d saved_Y=%0d host_return_injected=%0d", copy_count,
                 preserve_y ? 0 : 9, !preserve_y);
        $display("BOOT address=%h CPU=%0d opcodes=%0d RTIs=%0d A=%h X=%h Y=%h S=%h",
                 card_cpu_address, cpu_completed, opcodes, rtis,
                 dut.platform.card.card.processor.cpu.reg_a, dut.platform.card.card.processor.cpu.reg_x,
                 dut.platform.card.card.processor.cpu.reg_y, dut.platform.card.card.processor.cpu.reg_s);
