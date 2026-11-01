`timescale 1ns/1ps
module tb_card_display_state;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset, valid, complete, write, aux, double_hires, motor;
    reg [15:0] address;
    wire altchar, text_mode, hires, annunciator3, col80, mixed, page2, store80;
    wire active_page2, text_page_active, hires_page_active, display_trap, io_trap;
    wire [7:0] observed = {store80, page2, mixed, col80, annunciator3, hires, text_mode, altchar};
    reg [7:0] expected_state;
    reg [1:0] oracle [0:262143];
    reg [2:0] plans [0:255];
    reg [15:0] probes [0:63];
    reg [1023:0] oracle_path, plans_path, probes_path;
    integer mode, bit_index, wait_tick, dhr, mot, bank, direction, probe;
    integer cursor = 0;
    reg [15:0] switch_address;

    card_display_state dut (.*);

    function automatic [15:0] off_address(input integer bit_number);
        case (bit_number)
            0: off_address = 16'hC00E;
            1: off_address = 16'hC050;
            2: off_address = 16'hC056;
            3: off_address = 16'hC05E;
            4: off_address = 16'hC00C;
            5: off_address = 16'hC052;
            6: off_address = 16'hC054;
            7: off_address = 16'hC000;
        endcase
    endfunction

    task automatic check_state;
        begin
            #1;
            if (observed !== expected_state)
                $fatal(1, "state expected=%h observed=%h address=%h", expected_state, observed, address);
        end
    endtask

    initial begin
        if (!$value$plusargs("oracle=%s", oracle_path) ||
            !$value$plusargs("plans=%s", plans_path) ||
            !$value$plusargs("probes=%s", probes_path)) $fatal(1, "missing inputs");
        $readmemh(oracle_path, oracle);
        $readmemh(plans_path, plans);
        $readmemh(probes_path, probes);
        reset = 1;
        valid = 1;
        complete = 1;
        write = 1;
        aux = 0;
        motor = 0;
        double_hires = 0;
        address = 16'hC00F;
        expected_state = 0;
        @(posedge clk);
        check_state();
        if (display_trap || io_trap) $fatal(1, "reset trap");
        @(negedge clk);
        reset = 0;
        for (mode = 0; mode < 256; mode = mode + 1) begin
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                switch_address = off_address(bit_index) | {15'b0, mode[bit_index]};
                address = off_address(bit_index) | {15'b0, !expected_state[bit_index]};
                // Read/write latches use both access directions across the sweep.
                write = bit_index == 0 || bit_index == 4 || bit_index == 7 || mode[0];
                valid = 1;
                complete = 0;
                repeat (3) begin
                    @(posedge clk);
                    check_state();
                    @(negedge clk);
                end
                valid = 0;
                complete = 1;
                @(posedge clk);
                check_state();
                if (display_trap || io_trap) $fatal(1, "invalid trap");
                @(negedge clk);
                valid = 1;
                address = switch_address;
                expected_state[bit_index] = mode[bit_index];
                @(posedge clk);
                check_state();
                @(negedge clk);
                // A read of a write-only switch must not change its latch.
                if (bit_index == 0 || bit_index == 4 || bit_index == 7) begin
                    address = switch_address ^ 16'h0001;
                    write = 0;
                    @(posedge clk);
                    check_state();
                    @(negedge clk);
                end
            end
            if ({active_page2, hires_page_active, text_page_active} !== plans[mode])
                $fatal(1, "page plan mode=%h", mode);
            complete = 0;
            for (dhr = 0; dhr < 2; dhr = dhr + 1)
                for (mot = 0; mot < 2; mot = mot + 1)
                    for (bank = 0; bank < 2; bank = bank + 1)
                        for (direction = 0; direction < 2; direction = direction + 1)
                            for (probe = 0; probe < 64; probe = probe + 1) begin
                                double_hires = dhr != 0;
                                motor = mot != 0;
                                aux = bank != 0;
                                write = direction != 0;
                                address = probes[probe];
                                #1;
                                if ({io_trap, display_trap} !== oracle[cursor])
                                    $fatal(1, "decode mode=%h address=%h aux=%b wr=%b dhr=%b motor=%b expected=%b actual=%b%b",
                                           mode, address, aux, write, double_hires, motor,
                                           oracle[cursor], io_trap, display_trap);
                                cursor = cursor + 1;
                            end
            @(negedge clk);
        end
        // Non-display accesses must leave state intact after completion.
        valid = 1;
        complete = 1;
        write = 1;
        address = 16'hC05D;
        @(posedge clk);
        check_state();
        @(negedge clk);
        // Reset wins over a completed switch and suppresses trap outputs.
        reset = 1;
        address = 16'hC001;
        expected_state = 0;
        @(posedge clk);
        check_state();
        if (display_trap || io_trap) $fatal(1, "reset trap");
        if (cursor != 262144) $fatal(1, "oracle length");
        $display("PASS states=256 held_switches=2048 invalid_completions=2048 readonly=768 classifications=%0d reset_priority=1", cursor);
        $finish;
    end
endmodule
