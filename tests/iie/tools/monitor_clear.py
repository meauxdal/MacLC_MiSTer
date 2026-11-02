#!/usr/bin/env python3
"""Continue the combined transition through original monitor clear stores."""
from prepare_runtime import WORK
from check_runtime import linux
from monitor_render import glyph_input, oracle


def prepare_bench(bench, driver, cells):
    tag = f'transition-clear-code{driver}-{cells}'
    marker = '    integer render_reads = 0, render_acks = 0, render_commits = 0, render_index;'
    assert marker in bench
    bench = bench.replace(marker, marker + '''
    reg service_return = 0, clear_seen = 0, clear_ack = 0, clear_committed = 0;
    reg [15:0] clear_address;
    reg [15:0] clear_initial_main [0:511];
    reg [15:0] clear_initial_aux [0:511];
    integer clear_done = 0, clear_reads = 0, clear_acks = 0, clear_commits = 0;
    integer clear_row, clear_col, clear_expected, clear_index;''')
    bench = bench.replace("card_cpu == 16'hFBDF) begin", "card_cpu == 16'hFBDF && !service_return) begin")
    marker = '''                $display("PASS consecutive Conf cleanup, upload, initialization, lookup setup, first display and service 1 ACK/return; register-preserving card RTI to FBDF");
                $finish;'''
    assert marker in bench
    bench = bench.replace(marker, '''                for (clear_index = 0; clear_index < 512; clear_index = clear_index + 1) begin
                    clear_initial_main[clear_index] = memory[17'h00200 + clear_index];
                    clear_initial_aux[clear_index] = memory[17'h08200 + clear_index];
                end
                service_return <= 1;
                $display("PHASE combined transition service 1 ACK/return and register-preserving RTI verified");''')
    offset = bench.index('            if (ticks >')
    bench = bench[:offset] + '''            if (service_return && capture_valid && !clear_seen && clear_done < CELL_COUNT) begin
                clear_row = clear_done / 40;
                clear_col = clear_done % 40;
                clear_expected = 16'h0400 + (clear_row % 8)*128 + (clear_row / 8)*40 + clear_col;
                if (capture_status != 8'h42 || capture_address != clear_expected || capture_data != 8'hA0)
                    $fatal(1, "monitor clear capture mismatch cell=%0d address=%h expected=%h status=%h data=%h",
                        clear_done, capture_address, clear_expected, capture_status, capture_data);
                if (memory[capture_address >> 1][8*capture_address[0] +: 8] !==
                    clear_initial_main[(capture_address - 16'h0400) >> 1][8*capture_address[0] +: 8])
                    $fatal(1, "monitor clear changed before capture cell=%0d", clear_done);
                clear_seen <= 1;
                clear_address <= capture_address;
            end
            if (clear_seen && !clear_ack) begin
                if (memory[clear_address >> 1][8*clear_address[0] +: 8] !==
                    clear_initial_main[(clear_address - 16'h0400) >> 1][8*clear_address[0] +: 8] ||
                    (mem_valid && !mem_rsp_valid && mem_write && mem_addr == (clear_address >> 1)))
                    $fatal(1, "monitor clear write before ACK cell=%0d", clear_done);
            end
            if (clear_seen && card.req_valid && card.req_ready && !card.req_word && card.req_offset == 6'h0C) begin
                if (card.req_write) begin
                    clear_ack <= 1;
                    clear_acks <= clear_acks + 1;
                end else clear_reads <= clear_reads + 1;
            end
            if (clear_seen && card.card.cpu_ready && card.card.cpu_write && card_cpu == clear_address) begin
                if (!clear_ack || capture_valid || memory[clear_address >> 1][8*clear_address[0] +: 8] != 8'hA0)
                    $fatal(1, "monitor clear commit mismatch cell=%0d", clear_done);
                clear_committed <= 1;
                clear_commits <= clear_commits + 1;
            end
            if (clear_ack && !as_n && rw_n && address == 32'h0020281C) begin
                if (!clear_committed || clear_reads != 2 || clear_acks != 1 || clear_commits != 1 ||
                    world[(16'hB7EE >> 1) + clear_address - 16'h0400] != 16'h00A0)
                    $fatal(1, "monitor clear return/cache mismatch cell=%0d reads=%0d acks=%0d commits=%0d",
                        clear_done, clear_reads, clear_acks, clear_commits);
                clear_done <= clear_done + 1;
                if (clear_done + 1 == CELL_COUNT) begin
                    for (clear_index = 0; clear_index < CELL_COUNT; clear_index = clear_index + 1) begin
                        clear_row = clear_index / 40;
                        clear_col = clear_index % 40;
                        clear_expected = 16'h0400 + (clear_row % 8)*128 + (clear_row / 8)*40 + clear_col;
                        if (memory[clear_expected >> 1][8*(clear_expected % 2) +: 8] != 8'hA0 ||
                            memory[(17'h10000 + clear_expected) >> 1][8*(clear_expected % 2) +: 8] !==
                                clear_initial_aux[(clear_expected - 16'h0400) >> 1][8*(clear_expected % 2) +: 8] ||
                            world[(16'hB7EE >> 1) + clear_expected - 16'h0400] != 16'h00A0)
                            $fatal(1, "monitor clear memory/cache mismatch cell=%0d", clear_index);
                    end
                    $writememh("FRAME_OUTPUT", frame);
                    $writememh("PAGE_OUTPUT", memory, 17'h00200, 17'h003FF);
                    $display("PASS combined transition and %0d original monitor clear ACKs, commits, cache cells and host polling returns; pixel verification follows", CELL_COUNT);
                    $finish;
                end
                clear_seen <= 0;
                clear_ack <= 0;
                clear_committed <= 0;
                clear_reads <= 0;
                clear_acks <= 0;
                clear_commits <= 0;
            end
''' + bench[offset:]
    bench = bench.replace('CELL_COUNT', str(cells))
    bench = bench.replace('FRAME_OUTPUT', linux(WORK / f'{tag}-frame.hex'))
    bench = bench.replace('PAGE_OUTPUT', linux(WORK / f'{tag}-page.hex'))
    bench = bench.replace('ticks > 10000000)', 'ticks > 20000000)')
    if cells == 960:
        bench = bench.replace("if (card_cpu != 16'hFBDD)", "if (card_cpu != 16'hFBDD && card_cpu != 16'hFB63)")
    return bench


def check_pixels(driver, cells):
    tag = f'transition-clear-code{driver}-{cells}'
    def read_words(path):
        return [int(word, 16) for word in path.read_text().splitlines() if word and not word.startswith('//')]
    page_path = WORK / f'{tag}-page.hex'
    frame_path = WORK / f'{tag}-frame.hex'
    page = b''.join(word.to_bytes(2, 'little') for word in read_words(page_path))
    frame = b''.join(word.to_bytes(2, 'big') for word in read_words(frame_path))
    assert len(page) == 1024
    for cell in range(cells):
        row, col = divmod(cell, 40)
        offset = (row % 8)*128 + (row // 8)*40 + col
        assert page[offset] == 0xa0, f'monitor clear page mismatch cell={cell}'
    glyph, _ = glyph_input()
    functions, _ = oracle(glyph.read_bytes())
    assert frame == functions['expected_frame'](driver, page), 'monitor clear text pixels or framebuffer guards mismatch'
    print('PASS transition clear framebuffer and guards match independent text oracle')
    return [page_path, frame_path]
