    reg [7:0] input_buffer [0:255];
    integer buffer_writes = 0;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.test_release_key && cpu_ready && dut.platform.card.card.cpu_write &&
            card_cpu_address >= 16'h0200 && card_cpu_address < 16'h0300) begin
            buffer_writes = buffer_writes + 1;
            $display("BUFFER_WRITE address=%h data=%h", card_cpu_address, dut.platform.card.card.cpu_wdata);
        end
    end
    task check_echo;
        reg [7:0] value, text_byte;
        begin
            value = raw_key == 'h15 ? 8'hA0 : raw_key == 'h7F ? 8'h88 : 8'hC1;
            if (backing('h200) !== value) $fatal(1, "input buffer store missing");
            if (raw_key != 'h7F && backing('h501) !== value) $fatal(1, "key echo store missing");
            if (card_cpu_address !== 16'hC267 || buffer_writes != 1 || prompt_writes != 8 ||
                dut.platform.card.card.processor.cpu.reg_x !== (raw_key == 'h7F ? 8'd0 : 8'd1) ||
                dut.platform.card.card.processor.cpu.reg_s !== 8'hEF ||
                backing('h24) !== (raw_key == 'h7F ? 8'd1 : 8'd2) ||
                backing('h25) !== (raw_key == 'h7F ? 8'd3 : 8'd2) ||
                {backing('h29), backing('h28)} !== (raw_key == 'h7F ? 16'h0580 : 16'h0500) ||
                {backing('h4F), backing('h4E)} !== 16'h0105 ||
                dut.platform.card.card.keyboard !== 8'(raw_key) || keyboard_pulses != 1 ||
                key_reads != 2 || key_clears != 1 || !dut.platform.card.card.internal_rom)
                $fatal(1, "original echo state mismatch");
            for (integer offset = 1; offset < 256; offset = offset + 1)
                if (backing('h200 + offset) !== input_buffer[offset])
                    $fatal(1, "input buffer extent mismatch offset=%h", offset);
            for (integer offset = 0; offset < 1024; offset = offset + 1) begin
                text_byte = cold_text[offset];
                case (offset)
                    'h100: text_byte = 8'hDD;
                    'h101: text_byte = raw_key == 'h7F ? 8'hA0 : value;
                    'h102: if (raw_key != 'h7F) text_byte = 8'h60;
                    'h180: if (raw_key == 'h7F) text_byte = 8'hDD;
                    'h181: if (raw_key == 'h7F) text_byte = 8'h60;
                    'h3F8: text_byte = 8'h31;
                    default: ;
                endcase
                if (backing('h400 + offset) !== text_byte || backing('h10400 + offset) !== cold_aux[offset])
                    $fatal(1, "echo text bank mismatch offset=%h", offset);
            end
            $display("ECHO_RESULT raw=%h buffer=%h CH=%h CV=%h X=%h stack=ef seed=0105",
                     8'(raw_key), value, backing('h24), backing('h25), dut.platform.card.card.processor.cpu.reg_x);
        end
    endtask
