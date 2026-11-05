#!/usr/bin/env python3
"""Continue the combined clear through the banner to the boot-service request."""
from prepare_runtime import ROOT, WORK
from check_runtime import linux
from monitor_render import glyph_input, oracle


def prepare_bench(bench, driver):
    monitor = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    assert monitor.read_bytes()[0x3f0a:0x3f13] == bytes.fromhex('c1 f0 f0 ec e5 a0 af af e5')
    marker = '    integer clear_row, clear_col, clear_expected, clear_index;'
    assert bench.count(marker) == 1
    bench = bench.replace(marker, marker + '''
    reg clear_return = 0, banner_return = 0, banner_ack = 0, boot_opcode = 0;
    reg [4:0] banner_saved = 0, banner_restored = 0;
    reg [15:0] boot_main [0:511], boot_aux [0:511];
    reg [7:0] banner_text [0:8];
    integer banner_reads = 0, banner_acks = 0, banner_stores = 0;
    integer boot_index, boot_address;
    reg [7:0] boot_expected;''')
    marker = '''                    $display("PASS combined transition and %0d original monitor clear ACKs, commits, cache cells and host polling returns; pixel verification follows", 960);
                    $finish;'''
    assert bench.count(marker) == 1
    bench = bench.replace(marker, '''                    for (boot_index = 0; boot_index < 512; boot_index = boot_index + 1) begin
                        boot_main[boot_index] = memory[17'h00200 + boot_index];
                        boot_aux[boot_index] = memory[17'h08200 + boot_index];
                    end
                    clear_return <= 1;
                    $display("PHASE full monitor clear verified; original service 4 and banner continue");''')
    marker = "if (card_cpu != 16'hFBDD && card_cpu != 16'hFB63)"
    assert bench.count(marker) == 1
    bench = bench.replace(marker, "if (card_cpu != 16'hFBDD && card_cpu != 16'hFB63 && card_cpu != 16'hFAB4)")
    offset = bench.index('            if (ticks >')
    bench = bench[:offset] + '''            if (clear_return && card.card.opcode02_complete && card_cpu == 16'hFAB4)
                boot_opcode <= 1;
            if (clear_return && card.card.cpu_ready &&
                card_cpu >= 16'hC078 && card_cpu <= 16'hC07C) begin
                if (card.card.cpu_write) banner_saved[card_cpu - 16'hC078] <= 1;
                else begin
                    banner_restored[card_cpu - 16'hC078] <= 1;
                    if (!banner_ack || (card_cpu == 16'hC07A && card.card.cpu_rdata != 9))
                        $fatal(1, "service 4 saved-register return mismatch address=%h data=%h", card_cpu, card.card.cpu_rdata);
                end
            end
            if (clear_return && capture_valid && capture_address == 16'hC07D &&
                capture_status == 8'hE0 && capture_data == 4 &&
                card.req_valid && card.req_ready && !card.req_word && card.req_offset == 6'h0C) begin
                if (card.req_write) begin
                    if (banner_saved != 5'b11111 || card.req_wdata[7:0] != 0)
                        $fatal(1, "service 4 ACK without saved registers");
                    banner_ack <= 1;
                    banner_acks <= banner_acks + 1;
                end else banner_reads <= banner_reads + 1;
            end
            if (clear_return && banner_ack && !banner_return && card.card.cpu_ready &&
                card.card.cpu_sync && card_cpu == 16'hFB65) begin
                if (!banner_ack || banner_saved != 5'b11111 || banner_restored != 5'b11111 ||
                    banner_reads != 2 || banner_acks != 1 || rti_count != 2 ||
                    card.card.processor.cpu.reg_a != saved_a ||
                    card.card.processor.cpu.reg_x != saved_x || card.card.processor.cpu.reg_y != 9 ||
                    card.card.processor.cpu.reg_s != saved_s || card.card.processor.cpu.reg_p != saved_p)
                    $fatal(1, "service 4 return ack=%b saved=%b restored=%b reads=%0d acks=%0d rti=%0d A=%h/%h X=%h/%h Y=%h/09 S=%h/%h P=%h/%h",
                        banner_ack, banner_saved, banner_restored, banner_reads, banner_acks, rti_count,
                        card.card.processor.cpu.reg_a, saved_a, card.card.processor.cpu.reg_x, saved_x,
                        card.card.processor.cpu.reg_y, card.card.processor.cpu.reg_s, saved_s,
                        card.card.processor.cpu.reg_p, saved_p);
                banner_return <= 1;
            end
            if (banner_return && card.card.cpu_ready && card.card.cpu_write &&
                card_cpu >= 16'h0400 && card_cpu < 16'h0800) begin
                if (banner_stores >= 9 || card_cpu != 16'h0417 - banner_stores ||
                    card.card.cpu_wdata != banner_text[8 - banner_stores])
                    $fatal(1, "original banner store mismatch index=%0d address=%h data=%h",
                        banner_stores, card_cpu, card.card.cpu_wdata);
                banner_stores <= banner_stores + 1;
            end
            if (clear_return && capture_valid && capture_address == 16'hC07D &&
                capture_status == 8'hE0 && capture_data == 2) begin
                if (!banner_return || !boot_opcode || banner_stores != 9)
                    $fatal(1, "boot request without original banner/receiver completion pc=%h", card.card.instruction_address);
                for (boot_index = 0; boot_index < 1024; boot_index = boot_index + 1) begin
                    boot_address = 16'h0400 + boot_index;
                    boot_expected = boot_main[boot_index >> 1][8*(boot_index % 2) +: 8];
                    if (boot_index >= 15 && boot_index < 24) boot_expected = banner_text[boot_index - 15];
                    if (memory[boot_address >> 1][8*(boot_address % 2) +: 8] !== boot_expected ||
                        memory[(17'h10000 + boot_address) >> 1][8*(boot_address % 2) +: 8] !==
                            boot_aux[boot_index >> 1][8*(boot_index % 2) +: 8])
                        $fatal(1, "banner main/aux text mismatch offset=%h", boot_index);
                end
                for (boot_index = 0; boot_index < 9; boot_index = boot_index + 1)
                    if (world[(16'hB7EE >> 1) + 15 + boot_index][7:0] !== banner_text[boot_index])
                        $fatal(1, "banner cache mismatch index=%0d", boot_index);
                $writememh("BOOT_FRAME_OUTPUT", frame);
                $writememh("BOOT_PAGE_OUTPUT", memory, 17'h00200, 17'h003FF);
                $writememh("BOOT_CACHE_OUTPUT", world, (16'hB7EE >> 1), (16'hB7EE >> 1) + 1023);
                $display("PASS combined transition, full clear, original service 4 Y=9 return and nine banner stores; service 2 held before host dispatch; pixel verification follows");
                $finish;
            end
''' + bench[offset:]
    # Original Monx 2606 $FF0A-$FF12, in screen order.
    setup = '\n'.join(f"        banner_text[{i}] = 8'h{value:02X};"
                      for i, value in enumerate(bytes.fromhex('c1 f0 f0 ec e5 a0 af af e5')))
    marker = '        repeat (10) @(negedge clk);'
    assert bench.count(marker) == 1
    bench = bench.replace(marker, setup + '\n' + marker)
    tag = f'transition-boot-code{driver}'
    bench = bench.replace('BOOT_FRAME_OUTPUT', linux(WORK / f'{tag}-frame.hex'))
    bench = bench.replace('BOOT_PAGE_OUTPUT', linux(WORK / f'{tag}-page.hex'))
    bench = bench.replace('BOOT_CACHE_OUTPUT', linux(WORK / f'{tag}-cache.hex'))
    return bench


def check_pixels(driver):
    tag = f'transition-boot-code{driver}'

    def read_words(path):
        return [int(word, 16) for word in path.read_text().splitlines()
                if word and not word.startswith('//')]

    page_path, frame_path = (WORK / f'{tag}-{kind}.hex' for kind in ('page', 'frame'))
    page = b''.join(word.to_bytes(2, 'little') for word in read_words(page_path))
    frame = b''.join(word.to_bytes(2, 'big') for word in read_words(frame_path))
    assert len(page) == 1024 and page[15:24] == bytes.fromhex('c1 f0 f0 ec e5 a0 af af e5'), 'original banner missing'
    # Service 4 adds a host message to the cache without changing card RAM.
    original = (ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin').read_bytes()
    visible = bytearray(page)
    visible[0x250:0x2f8] = bytes(value | 128 for value in original[0x1e14:0x1ebc])
    cache_path = WORK / f'{tag}-cache.hex'
    cache = read_words(cache_path)
    assert len(cache) == 1024
    assert bytes(word & 255 for word in cache[0x250:0x2f8]) == visible[0x250:0x2f8], 'service 4 message cache mismatch'
    glyph, _ = glyph_input()
    functions, _ = oracle(glyph.read_bytes())
    for _, _, address in functions['visible_cells']():
        assert cache[address - 0x400] == visible[address - 0x400], 'visible banner/message cache mismatch or dirty cell'
    assert frame == functions['expected_frame'](driver, visible), 'boot banner pixels or framebuffer guards mismatch'
    print('PASS transition boot banner framebuffer and guards match independent text oracle')
    return [page_path, frame_path, cache_path]
