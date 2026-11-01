`timescale 1ns/1ps
module tb_card_wait_cpu_bus;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, fast, irq_n = 1, nmi_n = 1, block_requests = 0;
    wire ready = !block_requests;
    wire valid, completed, sample_tick, write, sync, vector_pull, waiting, stopped;
    wire high_ram_read, high_ram_write;
    wire [15:0] address;
    wire [16:0] ram_address;
    wire [7:0] write_data;
    reg [7:0] memory [0:65535];
    integer writes [0:65535];
    wire [7:0] read_data = valid ? memory[address] : 8'hEE;
    integer test_case, fast_arg, i, accepted_count = 0, completed_count = 0;
    integer irq_vectors = 0, nmi_vectors = 0, clocks = 0, ticks = 0;
    integer nmi_low_samples = 0;
    integer prior_accepted, prior_completed;
    reg [25:0] held_bus;
    reg held = 0;
    reg [7:0] marker;

    card_wait_cpu_bus dut (.*);

    always @(posedge clk) begin
        clocks = clocks + 1;
        if (clocks > 50000) $fatal(1, "timeout case=%0d pc=%h", test_case, address);
        if (reset) begin
            accepted_count = 0;
            completed_count = 0;
            irq_vectors = 0;
            nmi_vectors = 0;
            ticks = 0;
            nmi_low_samples = 0;
            held = 0;
            if (valid || completed || sample_tick) $fatal(1, "reset transaction");
        end else begin
            if (held && held_bus !== {address, write_data, write, sync})
                $fatal(1, "CPU bus changed without completion");
            held = !waiting && !stopped && !completed;
            held_bus = {address, write_data, write, sync};
            if (sample_tick) begin
                ticks = ticks + 1;
                if (!nmi_n) nmi_low_samples = nmi_low_samples + 1;
            end
            if (valid && ready) begin
                accepted_count = accepted_count + 1;
                if (write) begin
                    memory[address] = write_data;
                    writes[address] = writes[address] + 1;
                end
                if (vector_pull && address == 16'hFFFE) irq_vectors = irq_vectors + 1;
                if (vector_pull && address == 16'hFFFA) nmi_vectors = nmi_vectors + 1;
            end
            if (completed) completed_count = completed_count + 1;
            if (completed_count > accepted_count || accepted_count - completed_count > 1)
                $fatal(1, "transaction accounting");
            if ((waiting || stopped) && (valid || completed)) $fatal(1, "halt transaction");
        end
    end

    task automatic wait_ticks(input integer count);
        integer seen;
        begin
            seen = 0;
            while (seen < count) begin
                @(negedge clk);
                if (sample_tick) seen = seen + 1;
            end
        end
    endtask

    task automatic pulse_reset;
        begin
            reset = 1;
            repeat (2) @(negedge clk);
            if (valid || completed || waiting || stopped) $fatal(1, "reset did not clear CPU");
            irq_n = 1;
            nmi_n = 1;
            block_requests = 0;
            reset = 0;
        end
    endtask

    initial begin
        if (!$value$plusargs("case=%d", test_case) || !$value$plusargs("fast=%d", fast_arg))
            $fatal(1, "missing case or speed");
        fast = fast_arg != 0;
        for (i = 0; i < 65536; i = i + 1) begin
            memory[i] = 8'hEA;
            writes[i] = 0;
        end
        memory[16'h0011] = 0;
        memory[16'h0012] = 0;
        memory[16'h0200] = 0;
        memory[16'h0400] = 8'hC7;
        memory[16'hFFFC] = 8'h00; memory[16'hFFFD] = 8'h20;
        memory[16'hFFFA] = 8'h00; memory[16'hFFFB] = 8'h30;
        memory[16'hFFFE] = 8'h00; memory[16'hFFFF] = 8'h31;
        memory[16'h3000] = 8'hE6; memory[16'h3001] = 8'h11; memory[16'h3002] = 8'h40;
        memory[16'h3100] = 8'hE6; memory[16'h3101] = 8'h12; memory[16'h3102] = 8'h40;
        if (test_case < 3 || test_case >= 12) begin
            marker = 8'hA0 + 8'(test_case);
            memory[16'h2000] = test_case == 1 || test_case == 13 ? 8'h58 : 8'h78;
            memory[16'h2001] = 8'hEA;
            memory[16'h2002] = 8'hCB;
            memory[16'h2003] = 8'hA9; memory[16'h2004] = marker;
            memory[16'h2005] = 8'h8D; memory[16'h2006] = 0; memory[16'h2007] = 2;
            memory[16'h2008] = 8'hDB;
        end else begin
            marker = test_case == 3 || test_case == 5 || test_case == 8 || test_case == 10 ? 8'hC7 : 8'h5A;
            memory[16'h2000] = 8'h58; memory[16'h2001] = 8'hEA;
            memory[16'h2002] = 8'hA9; memory[16'h2003] = 8'h5A;
            memory[16'h2004] = marker == 8'hC7 ? 8'hAD : 8'h8D;
            memory[16'h2005] = 0; memory[16'h2006] = 4;
            memory[16'h2007] = 8'h8D; memory[16'h2008] = 0; memory[16'h2009] = 2;
            memory[16'h200A] = 8'hDB;
        end
        repeat (2) @(negedge clk);
        reset = 0;
        if (test_case < 3 || test_case >= 12) begin
            wait (waiting);
            @(negedge clk);
            prior_accepted = accepted_count;
            prior_completed = completed_count;
            wait_ticks(4);
            if (!waiting || accepted_count != prior_accepted || completed_count != prior_completed)
                $fatal(1, "WAI generated transactions");
            if (test_case == 12) begin
                // A low/high pulse wholly between sampling ticks is ignored.
                @(negedge clk);
                nmi_n = 0;
                @(negedge clk);
                nmi_n = 1;
                wait_ticks(4);
                if (!waiting || nmi_vectors || nmi_low_samples) $fatal(1, "unsampled NMI woke WAI");
            end
            if (test_case == 2 || test_case >= 12) nmi_n = 0;
            else irq_n = 0;
            wait_ticks(test_case == 14 ? 1 : 4);
            nmi_n = 1;
            irq_n = 1;
        end else if (test_case != 7) begin
            wait (valid && address == 16'h0400);
            if (test_case >= 10) begin
                wait (dut.response_pending);
                if (completed_count == accepted_count) $fatal(1, "missing buffered response");
                pulse_reset();
            end else begin
                block_requests = 1;
                wait_ticks(4);
                if (test_case == 3 || test_case == 4) irq_n = 0;
                if (test_case == 5 || test_case == 6) nmi_n = 0;
                wait_ticks(4);
                if ((test_case == 3 || test_case == 4) && !dut.cpu.irq_l2)
                    $fatal(1, "IRQ not sampled during held bus");
                if ((test_case == 5 || test_case == 6) && !dut.cpu.nmi_pending)
                    $fatal(1, "NMI not retained during held bus");
                nmi_n = 1;
                if (test_case == 8 || test_case == 9) begin
                    if (writes[16'h0400] != 0) $fatal(1, "unaccepted write committed");
                    pulse_reset();
                end else block_requests = 0;
            end
        end
        if (test_case == 3 || test_case == 4) begin
            wait (valid && vector_pull && address == 16'hFFFE);
            irq_n = 1;
        end
        wait (stopped);
        @(negedge clk);
        if (memory[16'h0200] !== marker || writes[16'h0200] != 1)
            $fatal(1, "result marker=%h actual=%h writes=%0d", marker, memory[16'h0200], writes[16'h0200]);
        if (accepted_count != completed_count || dut.response_pending) $fatal(1, "undrained stop");
        if (irq_vectors != ((test_case == 1 || test_case == 3 || test_case == 4) ? 1 : 0))
            $fatal(1, "IRQ count=%0d", irq_vectors);
        if (nmi_vectors != ((test_case == 2 || test_case == 5 || test_case == 6 || test_case >= 12) ? 1 : 0))
            $fatal(1, "NMI count=%0d", nmi_vectors);
        if (test_case == 14 && nmi_low_samples != 1) $fatal(1, "one-sample NMI width");
        if (memory[16'h0011] !== 8'(nmi_vectors) || memory[16'h0012] !== 8'(irq_vectors))
            $fatal(1, "interrupt handler result");
        if (marker == 8'h5A && writes[16'h0400] != (test_case == 11 ? 2 : 1))
            $fatal(1, "write not exactly once per acceptance: %0d", writes[16'h0400]);
        if (test_case == 7) begin
            prior_accepted = accepted_count;
            prior_completed = completed_count;
            irq_n = 0;
            nmi_n = 0;
            wait_ticks(8);
            if (!stopped || accepted_count != prior_accepted || completed_count != prior_completed)
                $fatal(1, "interrupt escaped STP");
            pulse_reset();
            wait (stopped);
            @(negedge clk);
            if (writes[16'h0200] != 2) $fatal(1, "reset did not escape STP");
        end
        $display("PASS case=%0d fast=%0d accepted=%0d completed=%0d IRQ=%0d NMI=%0d ticks=%0d writes0400=%0d",
                 test_case, fast_arg, accepted_count, completed_count, irq_vectors, nmi_vectors, ticks, writes[16'h0400]);
        $finish;
    end
endmodule
