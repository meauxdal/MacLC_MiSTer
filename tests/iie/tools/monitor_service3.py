#!/usr/bin/env python3
"""Continue the combined transition through the first service 3 return."""


def prepare_bench(bench):
    marker = '    reg bs2_seen = 0, bs2_ack = 0, bs2_return = 0;'
    assert bench.count(marker) == 1
    bench = bench.replace(marker, marker + '''
    reg bs3_seen = 0, bs3_ack = 0;
    reg [4:0] bs3_saved = 0, bs3_restored = 0;
    integer bs3_reads = 0, bs3_acks = 0;''')
    marker = "if (bs2_seen && capture_valid && capture_address == 16'hC07D &&\n                capture_status == 8'hE0 && capture_data == 3) begin"
    assert bench.count(marker) == 1
    bench = bench.replace(marker, marker.replace('if (bs2_seen &&', 'if (bs2_seen && !bs3_seen &&'))
    marker = '''                $display("PASS original service 2 selection and register return; service 3 held before host dispatch");
                $finish;'''
    assert bench.count(marker) == 1
    bench = bench.replace(marker, '''                bs3_seen <= 1;
                $display("PHASE original service 3 mismatch request");''')
    offset = bench.index('            if (ticks >')
    bench = bench[:offset] + '''            if (bs2_return && card.card.cpu_ready &&
                card_cpu >= 16'hC078 && card_cpu <= 16'hC07C) begin
                if (card.card.cpu_write) bs3_saved[card_cpu - 16'hC078] <= 1;
                else begin
                    bs3_restored[card_cpu - 16'hC078] <= 1;
                    // 65C02 P has no B storage; PLP/RTI ignore bit 4
                    if (!bs3_ack || (card_cpu == 16'hC07B &&
                        (card.card.cpu_rdata & 8'hEF) != (saved_p & 8'hED)))
                        $fatal(1, "service 3 register reply address=%h data=%h expected P=%h",
                            card_cpu, card.card.cpu_rdata, saved_p & 8'hED);
                end
            end
            if (bs3_seen && capture_valid && capture_address == 16'hC07D &&
                capture_status == 8'hE0 && capture_data == 3 &&
                card.req_valid && card.req_ready && !card.req_word && card.req_offset == 6'h0C) begin
                if (card.req_write) begin
                    if (bs3_saved != 5'b11111 || card.req_wdata[7:0] != 0)
                        $fatal(1, "service 3 ACK without saved registers");
                    bs3_ack <= 1;
                    bs3_acks <= bs3_acks + 1;
                end else bs3_reads <= bs3_reads + 1;
            end
            if (bs3_ack && card.card.cpu_ready && card.card.cpu_sync && card_cpu == 16'hFAC2) begin
                if (bs3_saved != 5'b11111 || bs3_restored != 5'b11111 || bs3_reads != 2 ||
                    bs3_acks != 1 || rti_count != 4 || card.card.processor.cpu.reg_a != saved_a ||
                    card.card.processor.cpu.reg_x != saved_x || card.card.processor.cpu.reg_y != saved_y ||
                    card.card.processor.cpu.reg_s != saved_s ||
                    card.card.processor.cpu.reg_p != (saved_p & 8'hFD) ||
                    saved_a != 8'hC5 || saved_y != 5 || memory[0] != 16'hC500)
                    $fatal(1, "service 3 return saved=%b restored=%b reads=%0d acks=%0d rti=%0d A=%h/%h X=%h/%h Y=%h/%h S=%h/%h P=%h/%h zp=%h",
                        bs3_saved, bs3_restored, bs3_reads, bs3_acks, rti_count,
                        card.card.processor.cpu.reg_a, saved_a, card.card.processor.cpu.reg_x, saved_x,
                        card.card.processor.cpu.reg_y, saved_y, card.card.processor.cpu.reg_s, saved_s,
                        card.card.processor.cpu.reg_p, saved_p & 8'hFD, memory[0]);
                $display("PASS original service 3 mismatch ACK and register return; monitor branch held");
                $finish;
            end
''' + bench[offset:]
    return bench
