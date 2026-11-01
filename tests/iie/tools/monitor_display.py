#!/usr/bin/env python3
"""Extend the TG68K upload fixture through initialized lores stores."""
import json
from pathlib import Path

from prepare_runtime import ROOT, WORK, sha, asset_path
from check_runtime import linux


def prepare_display(bench, driver, driver_image, control, cells):
    pins = ROOT / 'fixtures/experiments/card-display-init/results.json'
    run = next(r for r in json.loads(pins.read_text())['runs'] if r['driver'] == driver)
    snapshots = [asset_path(run['run_directory']) / n for n in ('world.bin', 'code-after.bin')]
    for path in snapshots:
        assert sha(path) == run['hashes'][path.name], 'changed initializer snapshot: ' + str(path)
    count_tag = '' if cells == 1 else f'-{cells}'
    fixture = f'monitor-display-code{driver}{count_tag}-' + ('control' if control else 'pass')
    world = bytearray(131072)
    original = (ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin').read_bytes()
    initial_world = snapshots[0].read_bytes()
    assert len(initial_world) == 0x5c49
    world[0xa6a0:0xa6a0 + len(initial_world)] = initial_world
    # Match the recovered mode-zero dispatch entry after switch setup.
    assert original[0xb5c:0xb60] == bytes.fromhex('00080001')
    world[0xf688:0xf68c] = original[0xb5c:0xb60]
    if control:
        destination = 0x10000 - 0x85e
        value = int.from_bytes(world[destination:destination + 4], 'big')
        world[destination:destination + 4] = (value + 1).to_bytes(4, 'big')
    world_image = WORK / f'{fixture}-world.hex'
    world_image.write_text(''.join(f'{int.from_bytes(world[i:i+2], "big"):04x}\n'
                                  for i in range(0, len(world), 2)), encoding='ascii')
    code = snapshots[1].read_bytes()
    table = 0x669c if driver == 5 else 0x5378
    assert len(code) == len(original)
    assert code[:table] == original[:table] and code[table + 4096:] == original[table + 4096:]
    code += bytes(65536 - len(code))
    driver_image.write_text(''.join(f'{int.from_bytes(code[i:i+2], "big"):04x}\n'
                                   for i in range(0, len(code), 2)), encoding='ascii')
    stride = 320 if driver == 5 else 80
    frame_size = stride * 480 + 128
    expected = bytearray([0x5a]) * frame_size
    # Monitor clear byte A0: upper color 0, lower color A.
    for cell in range(cells):
        row, col = divmod(cell, 40)
        for line in range(16):
            for pixel in range(14):
                x = (40 if driver == 5 else 32) + col * 14 + pixel
                y = 48 + row * 16 + line
                if driver == 5:
                    index, shift = 64 + y * stride + x // 2, 4 if x % 2 == 0 else 0
                    color = 15 if line < 8 else 12
                    expected[index] = (expected[index] & ~(15 << shift)) | (color << shift)
                else:
                    index, shift = 64 + y * stride + x // 8, 7 - x % 8
                    pattern = 0x3fff if line < 8 else 0x2aaa
                    expected[index] = (expected[index] & ~(1 << shift)) | (((pattern >> (13 - pixel)) & 1) << shift)
    expected_image = WORK / f'monitor-display-expected{driver}{count_tag}.hex'
    expected_image.write_text(''.join(f'{int.from_bytes(expected[i:i+2], "big"):04x}\n'
                                     for i in range(0, len(expected), 2)), encoding='ascii')
    frame_output = WORK / f'{fixture}-frame.hex'
    bench = bench.replace('reg [15:0] world [0:32767];', f'''reg [15:0] world [0:65535];
    reg [15:0] frame [0:{frame_size // 2 - 1}];
    reg [15:0] expected_frame [0:{frame_size // 2 - 1}];
    wire frame_access = address >= 32'h000FFFC0 && address < 32'h00100000 + {stride * 480 + 64};
    reg first_return = 0, display_seen = 0, display_ack = 0, display_committed = 0;
    reg [15:0] display_address;
    reg [7:0] display_value;
    integer display_index, display_reads = 0, display_acks = 0, display_commits = 0;
    integer display_done = 0, display_expected, display_row, display_col;''')
    bench = bench.replace("address[31:16] == 16'h002F", "(address[31:16] == 16'h002F || address[31:16] == 16'h0030)")
    bench = bench.replace('world[address[15:1]]', "world[(address - 32'h002F0000) >> 1]")
    bench = bench.replace('world[(address - 32\'h002F0000) >> 1] : rom[address[15:1]];',
        "world[(address - 32'h002F0000) >> 1] : frame_access ? frame[(address - 32'h000FFFC0) >> 1] : rom[address[15:1]];")
    bench = bench.replace('        if (card.card.opcode02_complete) begin', '''        if (frame_access && !as_n && !rw_n) begin
            if (!uds_n) frame[(address - 32'h000FFFC0) >> 1][15:8] <= data_out[15:8];
            if (!lds_n) frame[(address - 32'h000FFFC0) >> 1][7:0] <= data_out[7:0];
        end
        if (card.card.opcode02_complete) begin''')
    bench = bench.replace('for (integer i = 0; i < 32768; i = i + 1) world[i] = 0;',
        '$readmemh("' + linux(world_image) + f'''", world);
        for (integer i = 0; i < {frame_size // 2}; i = i + 1) frame[i] = 16'h5A5A;
        $readmemh("{linux(expected_image)}", expected_frame);''')
    bench = bench.replace("card_cpu == 16'hFBDF) begin", "card_cpu == 16'hFBDF && !first_return) begin")
    bench = bench.replace('''                $display("PASS original TG68K upload and driver service 1 ACK/return; card RTI to FBDF");
                $finish;''', '''                first_return <= 1;
            end
            if (first_return && capture_valid && !display_seen && display_done < CELL_COUNT) begin
                display_row = display_done / 40;
                display_col = display_done % 40;
                display_expected = 16'h0400 + (display_row % 8)*128 + (display_row / 8)*40 + display_col;
                if (capture_status != 8'h42 || capture_address != display_expected || capture_data != 8'hA0)
                    $fatal(1, "monitor display store mismatch cell=%0d address=%h expected=%h status=%h data=%h",
                        display_done, capture_address, display_expected, capture_status, capture_data);
                if (memory[capture_address >> 1][8*capture_address[0] +: 8] != 0)
                    $fatal(1, "display store committed before ACK");
                display_seen <= 1;
                display_address <= capture_address;
                display_value <= capture_data;
            end
            if (display_seen && card.req_valid && card.req_ready && !card.req_write &&
                !card.req_word && card.req_offset == 6'h0C)
                display_reads <= display_reads + 1;
            if (display_seen && card.req_valid && card.req_ready && card.req_write &&
                !card.req_word && card.req_offset == 6'h0C) begin
                display_ack <= 1;
                display_acks <= display_acks + 1;
            end
            if (display_seen && card.card.cpu_ready && card.card.cpu_write && card_cpu == display_address) begin
                if (!display_ack || capture_valid || memory[display_address >> 1][8*display_address[0] +: 8] != display_value)
                    $fatal(1, "display store was not committed after ACK");
                display_committed <= 1;
                display_commits <= display_commits + 1;
            end
            if (display_ack && !as_n && rw_n && address == 32'h0020281C) begin
                if (!display_committed || display_commits != 1 || display_reads != 2 || display_acks != 1 ||
                    world[(16'hB7EE >> 1) + display_address - 16'h0400] != 16'h00A0)
                    $fatal(1, "display handler returned without its store/cache update");
                display_done <= display_done + 1;
                if (display_done + 1 == CELL_COUNT) begin
                    for (display_index = 0; display_index < CELL_COUNT; display_index = display_index + 1) begin
                        display_row = display_index / 40;
                        display_col = display_index % 40;
                        display_expected = 16'h0400 + (display_row % 8)*128 + (display_row / 8)*40 + display_col;
                        if (memory[display_expected >> 1][8*(display_expected % 2) +: 8] != 8'hA0 ||
                            memory[(17'h10000 + display_expected) >> 1][8*(display_expected % 2) +: 8] != 0 ||
                            world[(16'hB7EE >> 1) + display_expected - 16'h0400] != 16'h00A0)
                            $fatal(1, "monitor display memory/cache mismatch cell=%0d", display_index);
                    end
                    $writememh("FRAME_OUTPUT", frame);
                    for (display_index = 0; display_index < FRAME_WORDS; display_index = display_index + 1)
                        if (frame[display_index] !== expected_frame[display_index]) begin
                            PIXEL_MISMATCH
                        end
                    PIXEL_MATCH
                    $display("PASS original TG68K %0d monitor display ACKs, commits, cache cells and rendered pixels", CELL_COUNT);
                    $finish;
                end
                display_seen <= 0;
                display_ack <= 0;
                display_committed <= 0;
                display_reads <= 0;
                display_acks <= 0;
                display_commits <= 0;''')
    bench = bench.replace('FRAME_OUTPUT', linux(frame_output)).replace('FRAME_WORDS', str(frame_size // 2))
    bench = bench.replace('CELL_COUNT', str(cells))
    bench = bench.replace('ticks > 100000)', f'ticks > {100000 + cells * 10000})')
    if cells == 960:
        bench = bench.replace("if (card_cpu != 16'hFBDD)", "if (card_cpu != 16'hFBDD && card_cpu != 16'hFB63)")
    mismatch = '$fatal(1, "display pixel mismatch word=%0d actual=%h expected=%h", display_index, frame[display_index], expected_frame[display_index]);'
    match = ''
    if control:
        mismatch = '''$display("PASS shifted display destination rejected by pixel check after original ACK/commit");
                        $finish;'''
        match = '$fatal(1, "shifted destination escaped pixel check");'
    bench = bench.replace('PIXEL_MISMATCH', mismatch).replace('PIXEL_MATCH', match)
    return bench, [Path(__file__), pins, *snapshots, world_image, expected_image, frame_output]
