    function [7:0] backing(input integer address);
        if (address[0]) backing = memory[address / 2][15:8];
        else backing = memory[address / 2][7:0];
    endfunction
    task check_idle;
        reg [7:0] text_byte;
        reg [15:0] seed;
        begin
            if (!cold_checked || !input_seen || prompt_writes != 4 ||
                dut.platform.card.card.idle_reads != 260 || expected['h24] !== 1 ||
                expected['h25] !== 2 || expected['h28] !== 0 || expected['h29] !== 5 ||
                dut.platform.card.card.processor.cpu.reg_s !== 8'hEC)
                $fatal(1, "prompt idle checkpoint mismatch");
            seed = {backing('h4F), backing('h4E)};
            if (seed !== input_seed + 16'd260)
                $fatal(1, "idle seed carry missing expected=%h actual=%h", input_seed + 16'd260, seed);
            for (integer byte_index = 0; byte_index < 1024; byte_index = byte_index + 1) begin
                case (byte_index)
                    'h100: text_byte = 8'hDD;
                    'h101: text_byte = 8'hFF;
                    'h3F8: text_byte = 8'h62;
                    default: text_byte = cold_text[byte_index];
                endcase
                if (backing('h400 + byte_index) !== text_byte ||
                    backing('h10400 + byte_index) !== cold_aux[byte_index])
                    $fatal(1, "prompt text bank mismatch offset=%h", byte_index);
            end
            $display("IDLE reads=260 seed=%h cursor=0501 prompt=dd cell=ff CH=01 CV=02", seed);
        end
    endtask
