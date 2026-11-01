#!/usr/bin/env python3
"""Bind original hires refresh to the held native-memory monitor bridge."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-hires-refresh'
PARENT = ROOT / 'fixtures/experiments/card-display-text80'
spec = importlib.util.spec_from_file_location('text_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, snapshot_inputs = parent.once, parent.sha, parent.snapshot_inputs
FIRST_ACK, LAST_ACK = 8214, 8223


def prepare(page):
    pins_path = PARENT / 'results-5-4a-00.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    assert sha(PARENT / 'prepare.py') == pins[str(PARENT / 'prepare.py')]
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = bench.read_text()
    marker = '        pause_cycles = int\'(cpu_completed);'
    text = once(text, marker, """        $readmemh(""" + '"' + (WORK / 'hires.hex').as_posix().replace('C:', '/mnt/c') + '"' + """, hires_fixture);
        for (i = 0; i < 16384; i = i + 1) begin
            expected['h2000 + i] = hires_fixture[i];
            if (i % 2 == 0) memory[('h2000 + i) / 2][7:0] = hires_fixture[i];
            else memory[('h2000 + i) / 2][15:8] = hires_fixture[i];
        end
""" + marker)
    text = once(text, '    integer pause_cycles, pause_captures;',
                '    integer pause_cycles, pause_captures;\n    reg [7:0] hires_fixture [0:16383];')
    text = once(text, 'bridge_index <= 1046;', f'bridge_index <= {FIRST_ACK};')
    text = once(text, 'bridge_index = 1047; bridge_index <= 1053;',
                f'bridge_index = {FIRST_ACK + 1}; bridge_index <= {LAST_ACK};')
    text = once(text, 'transact(0, 0, 33, (mask_seed & 3) | 24, 0);',
                f'transact(0, 0, 33, (mask_seed & 3) | {64 if page else 128}, 0);')
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), "dofile('fixtures/experiments/card-display-text80/bridge.lua')",
                "dofile('fixtures/experiments/card-hires-refresh/bridge.lua')")
    host = once(host, '        space:write_u32(world - 0x1236, card)', """        for _, region in ipairs({{0x320000, 0x4080}, {0x330000, 0x4080}, {0x340000, 0x7880}}) do
            for i = 0, region[2] - 1 do space:write_u8(region[1] + i, 0x5a) end
        end
        for i = 0, 16383 do
            space:write_u8(0x320040 + i, 0)
            space:write_u8(0x330040 + i, 0)
        end
        space:write_u32(world - 0x1222, 0x320040)
        space:write_u32(world - 0x122a, 0x330040)
        space:write_u32(world - 0x122e, 0x340040)
        space:write_u32(world - 0x1232, 0x343c40)
        if os.getenv('IIE_BAD_REFRESH') == '1' then
            space:write_u32(world - 0x1222, 0x320041)
        end
        space:write_u32(world - 0x1236, card)""")
    host = once(host, "                snapshot('main-after.bin', 0x280000, 0x685c)", """                snapshot('main-after.bin', 0x280000, 0x685c)
                local prefix = acks == 1 and 'mode-' or ''
                snapshot(prefix .. 'image.bin', 0x320000, 0x4080)
                snapshot(prefix .. 'dirty.bin', 0x330000, 0x4080)
                snapshot(prefix .. 'cache.bin', 0x340000, 0x7880)""")
    host = once(host, '        space:write_u32(0x3efff8, base + 0x2c4)',
                '        space:write_u32(0x3efff4, 0x2843d0)\n        space:write_u32(0x3efff8, base + 0x2c4)')
    host = once(host, "cpu.state['A7'].value = 0x3efff8", "cpu.state['A7'].value = 0x3efff4")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'bridge.lua', PARENT / 'prepare.py', pins_path]
