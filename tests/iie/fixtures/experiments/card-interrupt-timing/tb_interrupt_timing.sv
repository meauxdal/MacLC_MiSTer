`timescale 1ns/1ps
module tb_interrupt_timing;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, fast, nmi_n = 1;
    wire irq_n = 1, ready = 1;
    wire valid, completed, sample_tick, write, sync, vector_pull, waiting, stopped;
    wire high_ram_read, high_ram_write;
    wire [15:0] address;
    wire [16:0] ram_address;
    wire [7:0] write_data;
    reg [7:0] memory [0:65535];
    wire [7:0] read_data = memory[address];
    integer fast_arg, control, phase, width_index, width, i;
    integer vectors = 0, low_samples = 0, high_samples = 0, accepted = 0, completions = 0;
    integer tests = 0, captured = 0, missed = 0, clocks = 0;
    integer rearm_tests = 0, rearmed = 0, unarmed = 0;
    integer expected_vectors, prior_high_samples;
    card_wait_cpu_bus dut (.*);

    always @(posedge clk) begin
        clocks = clocks + 1;
        if (clocks > 8000000) $fatal(1, "watchdog");
        if (reset) begin
            vectors = 0;
            low_samples = 0;
            high_samples = 0;
            accepted = 0;
            completions = 0;
        end else begin
            if (sample_tick && !nmi_n) low_samples = low_samples + 1;
            if (sample_tick && nmi_n) high_samples = high_samples + 1;
            if (valid && ready) begin
                accepted = accepted + 1;
                if (write) memory[address] = write_data;
                if (vector_pull && address == 16'hFFFA) vectors = vectors + 1;
                if (vector_pull && address == 16'hFFFE) $fatal(1, "unexpected IRQ");
            end
            if (completed) completions = completions + 1;
            if (waiting && (valid || completed)) $fatal(1, "WAI bus activity");
            if (completions > accepted || accepted - completions > 1)
                $fatal(1, "transaction accounting");
        end
    end

    task wait_ticks(input integer count);
        integer seen;
        begin
            seen = 0;
            while (seen < count) begin
                @(negedge clk);
                if (sample_tick) seen = seen + 1;
            end
            // Pass the selected sampling edge before changing a pin.
            @(negedge clk);
        end
    endtask

    task restart;
        begin
            reset = 1;
            nmi_n = 1;
            memory[16'h11] = 0;
            repeat (3) @(negedge clk);
            reset = 0;
            wait (waiting);
            wait_ticks(4);
        end
    endtask

    task check_result(input integer expected_count);
        begin
            wait_ticks(32);
            if (!waiting || vectors != expected_count || memory[16'h11] !== 8'(expected_count))
                $fatal(1, "NMI count phase=%0d width=%0d vectors=%0d handler=%0d expected=%0d",
                       phase, width, vectors, memory[16'h11], expected_count);
            if (accepted != completions || dut.response_pending || dut.cpu.reg_s !== 8'hFD)
                $fatal(1, "NMI return/drain mismatch");
        end
    endtask

    initial begin
        if (!$value$plusargs("fast=%d", fast_arg)) $fatal(1, "missing rate");
        if (!$value$plusargs("control=%d", control)) control = 0;
        fast = fast_arg != 0;
        for (i = 0; i < 65536; i = i + 1) memory[i] = 8'hEA;
        memory[16'hFFFC] = 0; memory[16'hFFFD] = 8'h20;
        memory[16'hFFFA] = 0; memory[16'hFFFB] = 8'h30;
        memory[16'h2000] = 8'h78;
        memory[16'h2001] = 8'hCB;
        memory[16'h2002] = 8'h4C; memory[16'h2003] = 1; memory[16'h2004] = 8'h20;
        memory[16'h3000] = 8'hE6; memory[16'h3001] = 8'h11; memory[16'h3002] = 8'h40;

        if (!control) begin
            for (width_index = 0; width_index < 5; width_index = width_index + 1) begin
                case (width_index)
                    0: width = 1;
                    1: width = 2;
                    2: width = 32;
                    3: width = 64;
                    4: width = 128;
                endcase
                for (phase = 0; phase < 64; phase = phase + 1) begin
                    restart;
                    repeat (phase) @(negedge clk);
                    nmi_n = 0;
                    repeat (width) @(negedge clk);
                    nmi_n = 1;
                    expected_vectors = low_samples != 0 ? 1 : 0;
                    check_result(expected_vectors);
                    if (width >= 64 && expected_vectors != 1)
                        $fatal(1, "64-clock low missed sampling");
                    tests = tests + 1;
                    if (expected_vectors) captured = captured + 1;
                    else missed = missed + 1;
                end
            end

            for (width_index = 0; width_index < 5; width_index = width_index + 1) begin
                case (width_index)
                    0: width = 1;
                    1: width = 2;
                    2: width = 32;
                    3: width = 64;
                    4: width = 128;
                endcase
                for (phase = 0; phase < 64; phase = phase + 1) begin
                    restart;
                    nmi_n = 0;
                    check_result(1);
                    repeat (phase) @(negedge clk);
                    prior_high_samples = high_samples;
                    nmi_n = 1;
                    repeat (width) @(negedge clk);
                    nmi_n = 0;
                    expected_vectors = high_samples != prior_high_samples ? 2 : 1;
                    check_result(expected_vectors);
                    if (width >= 64 && expected_vectors != 2)
                        $fatal(1, "64-clock high did not rearm");
                    rearm_tests = rearm_tests + 1;
                    if (expected_vectors == 2) rearmed = rearmed + 1;
                    else unarmed = unarmed + 1;
                end
            end
        end

        // A held low must not retrigger after RTI; a sampled high rearms it.
        restart;
        nmi_n = 0;
        width = 0; phase = 0;
        check_result(1);
        check_result(1);
        nmi_n = 1;
        wait_ticks(4);
        nmi_n = 0;
        check_result(2);
        nmi_n = 1;
        check_result(2);
        if (!control && (!captured || !missed)) $fatal(1, "missing phase outcomes");
        if (!control && (!rearmed || !unarmed)) $fatal(1, "missing rearm outcomes");
        $display("PASS fast=%0d sweep=%0d captured=%0d missed=%0d high_sweep=%0d rearmed=%0d unarmed=%0d held_low=1 final_rearmed=2",
                 fast_arg, tests, captured, missed, rearm_tests, rearmed, unarmed);
        $finish;
    end
endmodule
