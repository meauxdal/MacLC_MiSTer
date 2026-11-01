    integer register_writes = 0, register_reads = 0, host_returns = 0;
    integer rti_contexts = 0;
    reg [7:0] returned_regs [0:4];
    reg [7:0] return_value;
    integer register_index;
    function integer write_index(input integer count);
        case (count % 5)
            0: write_index = 0;
            1: write_index = 1;
            2: write_index = 2;
            3: write_index = 4;
            default: write_index = 3;
        endcase
    endfunction
    function integer read_index(input integer count);
        read_index = 4 - count % 5;
    endfunction
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.read_release && capture_valid &&
            capture_address >= 16'hC078 && capture_address <= 16'hC07C) begin
            register_index = read_index(host_returns);
            return_value = returned_regs[register_index];
            if (host_returns >= 5 && register_index == 2) return_value = 9;
            if (capture_address !== 16'hC078 + 16'(register_index) ||
                capture_status !== 8'hE1 ||
                dut.platform.card.card.sidefx_wdata[7:0] !== return_value)
                $fatal(1, "host register return mismatch number=%0d address=%h expected=%h actual=%h",
                       host_returns, capture_address, return_value, dut.platform.card.card.sidefx_wdata);
            host_returns = host_returns + 1;
        end
        if (cpu_ready && dut.platform.card.card.service_register) begin
            if (dut.platform.card.card.cpu_write) begin
                register_index = write_index(register_writes);
                if (card_cpu_address !== 16'hC078 + 16'(register_index))
                    $fatal(1, "saved register write order");
                case (register_index)
                    0: return_value = saved_a;
                    1: return_value = saved_x;
                    2: return_value = saved_y;
                    3: return_value = expected['h100 + 32'(8'(saved_s - 2))];
                    default: return_value = saved_s - 3;
                endcase
                if (dut.platform.card.card.cpu_wdata !== return_value)
                    $fatal(1, "saved register write value");
                returned_regs[register_index] = return_value;
                $display("SAVE register=%0d value=%h", register_index, return_value);
                register_writes = register_writes + 1;
            end else begin
                register_index = read_index(register_reads);
                return_value = returned_regs[register_index];
                if (register_reads >= 5 && register_index == 2) return_value = 9;
                if (card_cpu_address !== 16'hC078 + 16'(register_index) ||
                    dut.platform.card.card.cpu_rdata !== return_value || host_returns != register_reads + 1)
                    $fatal(1, "saved register completion mismatch");
                $display("RESTORE register=%0d value=%h", register_index, return_value);
                register_reads = register_reads + 1;
            end
        end
        if (cpu_ready && dut.platform.card.card.cpu_sync &&
            ((card_cpu_address == 16'hFBDF && register_reads == 5 && rti_contexts == 0) ||
             (card_cpu_address == 16'hFB65 && register_reads == 10 && rti_contexts == 1))) begin
            if (rtis != (card_cpu_address == 16'hFBDF ? 1 : 2) ||
                dut.platform.card.card.processor.cpu.reg_a !== saved_a ||
                dut.platform.card.card.processor.cpu.reg_x !== saved_x ||
                dut.platform.card.card.processor.cpu.reg_y !== (card_cpu_address == 16'hFBDF ? saved_y : 8'd9) ||
                dut.platform.card.card.processor.cpu.reg_s !== saved_s ||
                dut.platform.card.card.processor.cpu.reg_p !== saved_p)
                $fatal(1, "saved register RTI context mismatch PC=%h RTIs=%0d A=%h/%h X=%h/%h Y=%h/%h S=%h/%h P=%h/%h",
                       card_cpu_address, rtis, dut.platform.card.card.processor.cpu.reg_a, saved_a,
                       dut.platform.card.card.processor.cpu.reg_x, saved_x,
                       dut.platform.card.card.processor.cpu.reg_y, saved_y,
                       dut.platform.card.card.processor.cpu.reg_s, saved_s,
                       dut.platform.card.card.processor.cpu.reg_p, saved_p);
            rti_contexts = rti_contexts + 1;
        end
    end
