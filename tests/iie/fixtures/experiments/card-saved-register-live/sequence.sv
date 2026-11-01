        bridge_active = 1;
        $display("READY");
        $fflush();
        bridge_index = 1;
        begin : exchange
            forever begin
                bridge_fields = $fscanf(32'h80000000, "%d %d %d %d %d", bridge_sequence,
                                       bridge_write, bridge_width, bridge_offset, bridge_value);
                if (bridge_fields != 5) $fatal(1, "incomplete bridge request");
                if (bridge_sequence == -1) disable exchange;
                if (bridge_sequence != bridge_index || bridge_index > 512 ||
                    (bridge_write != 0 && bridge_write != 1) ||
                    (bridge_width != 8 && bridge_width != 16)) $fatal(1, "invalid bridge request");
                if (bridge_write == 0 && bridge_width == 8 && bridge_offset == 1)
                    wait(capture_valid || boundary);
                transact(bridge_write, bridge_width == 16, bridge_offset, bridge_value, 0);
                $display("REPLY %0d %0d", bridge_sequence, bridge_reply);
                $fflush();
                bridge_index = bridge_index + 1;
            end
        end
        bridge_active = 0;
        wait(boundary);
        @(negedge clk_sys);
        if (card_cpu_address !== 16'hFAB4 || opcodes != 2 || rtis != 2 || nmis != 2 ||
            register_writes != 10 || register_reads != 10 || service_writes != 10 ||
            host_returns != 10 || switch_services != 5 || rti_contexts != 2)
            $fatal(1, "saved-register final coverage mismatch");
        for (i = 1; i <= 9; i = i + 1)
            if (expected['h40E + i] !== expected['h20000 + 'h3F09 + i])
                $fatal(1, "original nine-byte banner mismatch");
        for (row = 0; row < 24; row = row + 1)
            for (column = 0; column < 40; column = column + 1) begin
                text_address = (row % 8) * 128 + (row / 8) * 40 + column;
                if (expected['h400 + text_address] !==
                    (text_address >= 'h0F && text_address <= 'h17 ?
                     expected['h20000 + 'h3F09 + text_address - 'h0E] : 8'hA0) ||
                    expected['h10400 + text_address] !== 0)
                    $fatal(1, "original banner page mismatch");
            end
        $display("EXCHANGE writes=%0d reads=%0d returns=%0d captures=%0d transactions=%0d",
                 register_writes, register_reads, host_returns, capture_count, bridge_index - 1);
