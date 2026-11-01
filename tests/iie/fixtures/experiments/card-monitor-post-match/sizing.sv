        if (cold_entries != 1 || probe_count != 183 || probe_writes != 366 ||
            expected[0] !== 8'h4C || expected[3] !== 8'h4C ||
            expected[4] !== 8'h28 || expected[5] !== 8'hF1 ||
            expected['hA] !== 8'h4C || expected['hB] !== 8'h99 || expected['hC] !== 8'hE1 ||
            expected['h50] !== 0 || expected['h51] !== 8'hC0 ||
            expected['h76] !== 8'hFF || expected['h8F] !== 3 ||
            expected['h1FC] !== 1 || expected['h1FD] !== 1 ||
            dut.platform.card.card.processor.cpu.reg_s !== 8'hFA)
            $fatal(1, "cold-start initialization or RAM sizing mismatch");
        for (i = 0; i < 183; i = i + 1)
            if (expected[(9 + i) * 256] !== original_probe[i])
                $fatal(1, "cold sizing probe failed to restore page=%h", 8'(9 + i));
        for (i = 1; i <= 28; i = i + 1)
            if (expected['hB0 + i] !== expected['h20000 + 'h310A + i])
                $fatal(1, "cold-start tokenizer copy mismatch byte=%h", i);
        $display("SIZING entries=%0d probes=%0d writes=%0d next_page=%h next_PC=%h",
                 cold_entries, probe_count, probe_writes, expected['h51], card_cpu_address);
