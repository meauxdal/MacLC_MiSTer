#!/usr/bin/env python3
"""Connect original lookup generation and the first transition display handler."""
import ast
import json
from pathlib import Path

from prepare_runtime import ROOT, WORK, sha, asset_path
from check_runtime import linux


def oracle(glyphs):
    path = ROOT / 'fixtures/experiments/card-display-text/run.py'
    source = path.read_text().replace('    assert seen == set(range(256))\n', '')
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and
                 node.name in ('lookup_tables', 'visible_cells', 'expected_frame')]
    namespace = {'glyph_state': lambda: glyphs}
    exec(compile(tree, str(path), 'exec'), namespace)
    return namespace, path


def glyph_input():
    pins = ROOT / 'fixtures/experiments/card-continuous-glyph/results-5-slot6-init-key41.json'
    result = json.loads(pins.read_text())
    path = asset_path(result['run_directory']) / 'glyph-live.bin'
    assert sha(path) == result['capture_sha256'][path.name], 'changed QuickDraw glyph capture'
    assert path.stat().st_size == 4096
    return path, pins


def words(path, data):
    assert len(data) % 2 == 0
    path.write_text(''.join(f'{int.from_bytes(data[i:i+2], "big"):04x}\n'
                            for i in range(0, len(data), 2)), encoding='ascii')


def prepare_host(rom, driver):
    # Copy the supplied glyph image, then call unchanged CODE 1 $4300.
    call = bytes.fromhex('207c00370000227c002fdbee323c03ff22d851c9fffc'
                         '4eb90028430033fc00010000800a')
    start = rom.index(bytes.fromhex('4eb9002002a2'), 0x300, 0x1000)
    tail = bytes(rom[start:start + 18])
    rom[start:start + len(call) + len(tail)] = call + tail
    original = (ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin').read_bytes()
    clear_context = original[0x47e:0x484]
    assert clear_context == bytes.fromhex('08ac0003000d')
    # Preserve the original reset caller's exit from the upload memory context.
    reset = bytes.fromhex('2f0c') + clear_context + bytes.fromhex('4ef9002004ca')
    rom[0x180:0x180 + len(reset)] = reset
    return rom


def prepare_bench(bench, driver, setup_only=False, control=False, service=False, clear_cells=0):
    tag = f'transition-render-code{driver}' + ('-service' if service else '') + ('-control' if control else '')
    if clear_cells:
        tag += f'-clear-{clear_cells}'
    glyph, pins = glyph_input()
    functions, oracle_path = oracle(glyph.read_bytes())
    short, wide = functions['lookup_tables']()
    lookup_image = WORK / f'{tag}-lookup-expected.hex'
    words(lookup_image, short + wide)
    glyph_image = WORK / f'{tag}-glyph.hex'
    words(glyph_image, glyph.read_bytes())
    main = ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin'
    data = bytearray(main.read_bytes())
    assert data[0x4396:0x439e] == bytes.fromhex('000000000000ff00')
    if control:
        data[0x4396] ^= 1
    data += bytes(65536 - len(data))
    main_image = WORK / f'{tag}-main.hex'
    words(main_image, data)
    stride = 320 if driver == 5 else 80
    frame_words = (stride * 480 + 128) // 2
    bench = bench.replace('reg [15:0] world [0:65535];', f'''reg [15:0] world [0:65535];
    reg [15:0] main_code [0:32767];
    reg [15:0] glyph_source [0:2047];
    reg [15:0] lookup_expected [0:1535];
    reg [15:0] frame [0:{frame_words - 1}];
    wire frame_access = address >= 32'h000FFFC0 && address < 32'h00100000 + {stride * 480 + 64};
    reg lookup_done = 0, first_display = 0, display_ack = 0, service_return = 0;
    reg display_committed = 0, display_return = 0;
    integer render_reads = 0, render_acks = 0, render_commits = 0, render_index;''')
    bench = bench.replace('assign data_in = claim ? card_data :', '''assign data_in = claim ? card_data :
        address[31:16] == 16'h0028 ? main_code[address[15:1]] :
        address[31:16] == 16'h0037 ? glyph_source[address[11:1]] :
        frame_access ? frame[(address - 32'h000FFFC0) >> 1] :''')
    marker = '        if (mem_valid && !mem_rsp_valid) begin'
    assert marker in bench
    bench = bench.replace(marker, '''        if (!as_n && !rw_n && address[31:16] == 16'h0028)
            $fatal(1, "unexpected CODE 1 write");
        if (frame_access && !as_n && !rw_n) begin
            if (!uds_n) frame[(address - 32'h000FFFC0) >> 1][15:8] <= data_out[15:8];
            if (!lds_n) frame[(address - 32'h000FFFC0) >> 1][7:0] <= data_out[7:0];
        end
        if (!as_n && !rw_n && address == 32'h800A && !lookup_done) begin
            if (!initializer_done || data_out != 1 || card.card.cpu_running)
                $fatal(1, "lookup caller state mismatch");
            for (render_index = 0; render_index < 512; render_index = render_index + 1)
                if (world[(16'hD7EE >> 1) + render_index] !== lookup_expected[render_index])
                    $fatal(1, "short lookup mismatch word=%0d", render_index);
            for (render_index = 0; render_index < 1024; render_index = render_index + 1)
                if (world[(16'hC7EE >> 1) + render_index] !== lookup_expected[512 + render_index]) begin
                    LOOKUP_MISMATCH
                end
            LOOKUP_MATCH
            for (render_index = 0; render_index < 2048; render_index = render_index + 1)
                if (world[(16'hDBEE >> 1) + render_index] !== glyph_source[render_index])
                    $fatal(1, "glyph transfer mismatch word=%0d", render_index);
            lookup_done <= 1;
            $display("PHASE original CODE 1 lookup tables and supplied QuickDraw glyph image verified");
            SETUP_FINISH
        end
''' + marker, 1)
    marker = '            if (service_ack && card.card.cpu_ready && card.card.cpu_sync && card_cpu == 16\'hFBDF) begin'
    assert marker in bench
    bench = bench.replace(marker, marker.replace(') begin', ' && !service_return) begin'))
    marker = '''                $display("PASS consecutive Conf cleanup, upload, original reset helpers and service 1 RTI; automatic mapping");
                $finish;'''
    assert marker in bench
    bench = bench.replace(marker, '''                if (!lookup_done || !initializer_done)
                    $fatal(1, "service 1 reached before display setup");
                service_return <= 1;
                $display("PHASE service 1 ACK/return and register-preserving RTI verified");''')
    marker = '            if (ticks >'
    offset = bench.index(marker)
    bench = bench[:offset] + '''            if (service_return && !first_display && capture_valid) begin
                if (card.card.control[3] || capture_address != 16'h0400 || capture_status != 8'h42 || capture_data != 8'hA0)
                    $fatal(1, "first display capture mismatch address=%h status=%h data=%h", capture_address, capture_status, capture_data);
                first_display <= 1;
            end
            if (first_display && !display_return && card.req_valid && card.req_ready &&
                !card.req_word && card.req_offset == 6'h0C) begin
                if (card.req_write) begin
                    render_acks <= render_acks + 1;
                    display_ack <= 1;
                end else render_reads <= render_reads + 1;
            end
            if (first_display && !display_return && card.card.cpu_ready && card.card.cpu_write && card_cpu == 16'h0400) begin
                if (!display_ack || capture_valid || memory[17'h00200][7:0] != 8'hA0)
                    $fatal(1, "first display store did not commit after original ACK");
                render_commits <= render_commits + 1;
                display_committed <= 1;
            end
            if (display_ack && !display_return && !as_n && rw_n && address == 32'h0020281C) begin
                if (!display_committed || render_reads != 2 || render_acks != 1 || render_commits != 1 ||
                    world[16'hB7EE >> 1] != 16'h00A0)
                    $fatal(1, "first display handler return/cache mismatch reads=%0d acks=%0d commits=%0d", render_reads, render_acks, render_commits);
                $writememh("FRAME_OUTPUT", frame);
                $writememh("PAGE_OUTPUT", memory, 17'h00200, 17'h003FF);
                display_return <= 1;
                $display("PASS original service 1 and first display ACK, commit, cache and host polling return; pixel verification follows");
                DISPLAY_FINISH
            end
''' + bench[offset:]
    bench = bench.replace('DISPLAY_FINISH', '' if clear_cells else '$finish;')
    bench = bench.replace('FRAME_OUTPUT', linux(WORK / f'{tag}-frame.hex'))
    bench = bench.replace('PAGE_OUTPUT', linux(WORK / f'{tag}-page.hex'))
    mismatch = '$fatal(1, "wide lookup mismatch word=%0d", render_index);'
    match = ''
    if control:
        mismatch = '''if (render_index != 4 || world[(16'hC7EE >> 1) + render_index] != 16'h0100)
                        $fatal(1, "lookup control failed outside changed constant");
                    $display("PASS corrupted CODE 1 lookup constant rejected at wide entry 1"); $finish;'''
        match = '$fatal(1, "corrupted lookup constant escaped oracle");'
    bench = bench.replace('LOOKUP_MISMATCH', mismatch).replace('LOOKUP_MATCH', match)
    finish = '$display("PASS Conf cleanup, upload, original driver initialization and CODE 1 lookup setup; supplied QuickDraw glyphs verified before runtime reset"); $finish;' if setup_only else ''
    bench = bench.replace('SETUP_FINISH', finish)
    if not setup_only:
        bench = bench.replace('ticks > 2000000)', 'ticks > 10000000)')
    setup = f'''        $readmemh("{linux(main_image)}", main_code);
        $readmemh("{linux(glyph_image)}", glyph_source);
        $readmemh("{linux(lookup_image)}", lookup_expected);
        for (integer i = 0; i < {frame_words}; i = i + 1) frame[i] = 16'h5A5A;
'''
    bench = bench.replace('        repeat (10) @(negedge clk);', setup + '        repeat (10) @(negedge clk);')
    return bench, [Path(__file__), pins, glyph, oracle_path, main_image, glyph_image, lookup_image]


def check_pixels(driver, service=False, clear_cells=0):
    tag = f'transition-render-code{driver}' + ('-service' if service else '')
    if clear_cells:
        tag += f'-clear-{clear_cells}'
    def read_words(path):
        return [int(word, 16) for word in path.read_text().splitlines() if word and not word.startswith('//')]
    page = b''.join(word.to_bytes(2, 'little') for word in read_words(WORK / f'{tag}-page.hex'))
    frame = b''.join(word.to_bytes(2, 'big') for word in read_words(WORK / f'{tag}-frame.hex'))
    assert len(page) == 1024
    glyph, _ = glyph_input()
    functions, _ = oracle(glyph.read_bytes())
    expected = functions['expected_frame'](driver, page)
    assert frame == expected, 'first display pixels or framebuffer guards mismatch'
    print('PASS first transition display framebuffer and guards match independent text oracle')
    return [WORK / f'{tag}-page.hex', WORK / f'{tag}-frame.hex']
