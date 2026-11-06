#!/usr/bin/env python3
"""Continue the combined boot fixture through original service 2."""


def prepare_bench(bench):
    marker = '    reg clear_return = 0, banner_return = 0, banner_ack = 0, boot_opcode = 0;'
    assert bench.count(marker) == 1
    bench = bench.replace(marker, marker + '''
    reg bs2_seen = 0, bs2_ack = 0, bs2_return = 0;
    reg [4:0] bs2_saved = 0, bs2_restored = 0;
    integer bs2_reads = 0, bs2_acks = 0;''')
    marker = 'if (clear_return && card.card.cpu_ready &&\n                card_cpu >= 16\'hC078'
    assert bench.count(marker) == 1
    bench = bench.replace(marker, 'if (clear_return && !bs2_seen && card.card.cpu_ready &&\n                card_cpu >= 16\'hC078')
    marker = "if (card_cpu != 16'hFBDD && card_cpu != 16'hFB63 && card_cpu != 16'hFAB4)"
    assert bench.count(marker) == 1
    bench = bench.replace(marker, "if (card_cpu != 16'hFBDD && card_cpu != 16'hFB63 && card_cpu != 16'hFAB4 && card_cpu != 16'hFAC0)")
    marker = "if (clear_return && capture_valid && capture_address == 16'hC07D &&\n                capture_status == 8'hE0 && capture_data == 2) begin"
    assert bench.count(marker) == 1
    bench = bench.replace(marker, marker.replace('if (clear_return &&', 'if (clear_return && !bs2_seen &&'))
    marker = '''                $display("PASS combined transition, full clear, original service 4 Y=9 return and nine banner stores; service 2 held before host dispatch; pixel verification follows");
                $finish;'''
    assert bench.count(marker) == 1
    bench = bench.replace(marker, '''                world[16'hA7EC >> 1][15:8] <= 0;
                world[16'hF794 >> 1] <= 16'hA5B6;
                bs2_seen <= 1;
                $display("PHASE original service 2 request; supplied selection 6");''')
    offset = bench.index('            if (ticks >')
    bench = bench[:offset] + '''            if (banner_return && !bs2_return && card.card.cpu_ready &&
                card_cpu >= 16'hC078 && card_cpu <= 16'hC07C) begin
                if (card.card.cpu_write) bs2_saved[card_cpu - 16'hC078] <= 1;
                else begin
                    bs2_restored[card_cpu - 16'hC078] <= 1;
                    if (!bs2_ack || (card_cpu == 16'hC078 && card.card.cpu_rdata != 8'hC6))
                        $fatal(1, "service 2 register reply address=%h data=%h", card_cpu, card.card.cpu_rdata);
                end
            end
            if (bs2_seen && capture_valid && capture_address == 16'hC07D &&
                capture_status == 8'hE0 && capture_data == 2 &&
                card.req_valid && card.req_ready && !card.req_word && card.req_offset == 6'h0C) begin
                if (card.req_write) begin
                    if (bs2_saved != 5'b11111 || card.req_wdata[7:0] != 0)
                        $fatal(1, "service 2 ACK without saved registers");
                    bs2_ack <= 1;
                    bs2_acks <= bs2_acks + 1;
                end else bs2_reads <= bs2_reads + 1;
            end
            if (bs2_ack && !bs2_return && card.card.cpu_ready && card.card.cpu_sync && card_cpu == 16'hFAB6) begin
                if (bs2_saved != 5'b11111 || bs2_restored != 5'b11111 || bs2_reads != 2 ||
                    bs2_acks != 1 || rti_count != 3 || card.card.processor.cpu.reg_a != 8'hC6 ||
                    card.card.processor.cpu.reg_x != saved_x || card.card.processor.cpu.reg_y != saved_y ||
                    card.card.processor.cpu.reg_s != saved_s || card.card.processor.cpu.reg_p != saved_p)
                    $fatal(1, "service 2 return saved=%b restored=%b reads=%0d acks=%0d rti=%0d A=%h X=%h/%h Y=%h/%h S=%h/%h P=%h/%h",
                        bs2_saved, bs2_restored, bs2_reads, bs2_acks, rti_count,
                        card.card.processor.cpu.reg_a, card.card.processor.cpu.reg_x, saved_x,
                        card.card.processor.cpu.reg_y, saved_y, card.card.processor.cpu.reg_s, saved_s,
                        card.card.processor.cpu.reg_p, saved_p);
                bs2_return <= 1;
            end
            if (bs2_seen && capture_valid && capture_address == 16'hC07D &&
                capture_status == 8'hE0 && capture_data == 3) begin
                if (!bs2_return || rti_count != 3 || memory[0][15:8] != 8'hC5 ||
                    memory[0][7:0] != 0 || saved_a != 8'hC5 || saved_y != 5)
                    $fatal(1, "service 3 boundary return=%b rti=%0d zp=%h A=%h Y=%h",
                        bs2_return, rti_count, memory[0], saved_a, saved_y);
                $display("PASS original service 2 selection and register return; service 3 held before host dispatch");
                $finish;
            end
''' + bench[offset:]
    return bench
