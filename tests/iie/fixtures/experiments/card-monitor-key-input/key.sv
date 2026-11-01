    integer raw_key = 65, keyboard_pulses = 0, key_reads = 0, key_clears = 0;
    reg key_injected = 0, key_clear_seen = 0;
    reg [1023:0] key_instruction_path;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.keyboard_write) keyboard_pulses = keyboard_pulses + 1;
        if (key_injected && cpu_ready) begin
            if (card_cpu_address == 16'hC000 && !dut.platform.card.card.cpu_write) begin
                if (dut.platform.card.card.cpu_rdata !== (8'(raw_key) | 8'h80))
                    $fatal(1, "original key read mismatch");
                key_reads = key_reads + 1;
                $display("KEY_READ number=%0d data=%h", key_reads, dut.platform.card.card.cpu_rdata);
            end
            if (card_cpu_address == 16'hC010) begin
                if (!dut.platform.card.card.cpu_write) $fatal(1, "key clear was not an original write");
                key_clears = key_clears + 1;
                key_clear_seen = 1;
                $display("KEY_CLEAR completed=%0d cursor=%h stack=%h", key_clears, backing('h501), dut.platform.card.card.processor.cpu.reg_s);
            end
        end
    end
    always @(negedge clk_sys) begin
        if (key_clear_seen) begin
            if (dut.platform.card.card.keyboard !== 8'(raw_key))
                $fatal(1, "key clear completion missing latch=%h", dut.platform.card.card.keyboard);
            key_clear_seen = 0;
        end
    end
    task check_key;
        reg [7:0] text_byte;
        begin
            if (!key_injected || keyboard_pulses != 1 || key_reads != 2 || key_clears != 1 ||
                dut.platform.card.card.keyboard !== 8'(raw_key) || backing('h501) !== 8'hA0 ||
                backing('h500) !== 8'hDD || {backing('h4F), backing('h4E)} !== 16'h0105 ||
                dut.platform.card.card.processor.cpu.reg_s !== 8'hF4 || expected['h24] !== 1 || expected['h25] !== 2 ||
                dut.platform.card.card.internal_rom)
                $fatal(1, "original key result mismatch reads=%0d clears=%0d latch=%h", key_reads, key_clears, dut.platform.card.card.keyboard);
            if (prompt_writes != 5 || transaction_count != 331 || bridge_index - 1 != 314)
                $fatal(1, "key text or PDS accounting mismatch");
            for (integer byte_index = 0; byte_index < 1024; byte_index = byte_index + 1) begin
                case (byte_index)
                    'h100: text_byte = 8'hDD;
                    'h101: text_byte = 8'hA0;
                    'h3F8: text_byte = 8'h62;
                    default: text_byte = cold_text[byte_index];
                endcase
                if (backing('h400 + byte_index) !== text_byte ||
                    backing('h10400 + byte_index) !== cold_aux[byte_index])
                    $fatal(1, "key return text bank mismatch offset=%h", byte_index);
            end
            $display("PDS_ACCOUNT prelude=16 guest=314 delivery=1 total=%0d", transaction_count);
            $display("KEY_RESULT raw=%h reads=%0d clears=%0d latch=%h seed=0105 cursor=a0 stack=f4",
                     8'(raw_key), key_reads, key_clears, dut.platform.card.card.keyboard);
        end
    endtask
