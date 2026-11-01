#!/usr/bin/env python3
"""Bind paired double-hires refresh to the frozen PAGE1 mixed bridge."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-double-hires-live'
PARENT = ROOT / 'fixtures/experiments/card-hires-page1-mixed'
spec = importlib.util.spec_from_file_location('mixed_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, snapshot_inputs = parent.once, parent.sha, parent.snapshot_inputs


def prepare():
    pins_path = PARENT / 'results-5-24.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for path in (PARENT / 'prepare.py', PARENT / 'run.py'):
        assert sha(path) == pins[str(path)], path
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), '    reg [7:0] hires_fixture [0:16383];',
                '    reg [7:0] hires_fixture [0:16383];\n    reg [7:0] aux_fixture [0:16383];')
    text = once(text, "        pause_cycles = int'(cpu_completed);", """        for (i = 0; i < 1024; i = i + 1) begin
            expected['h800 + i] = 8'(i * 37 + (i / 256) * 11 + 61);
            expected['h10800 + i] = 8'(i * 53 + (i / 256) * 17 + 127);
            if (i % 2 == 0) begin
                memory[('h800 + i) / 2][7:0] = expected['h800 + i];
                memory[('h10800 + i) / 2][7:0] = expected['h10800 + i];
            end else begin
                memory[('h800 + i) / 2][15:8] = expected['h800 + i];
                memory[('h10800 + i) / 2][15:8] = expected['h10800 + i];
            end
        end
        $readmemh(""" + '"' + (WORK / 'aux.hex').as_posix().replace('C:', '/mnt/c') + '"' + """, aux_fixture);
        for (i = 0; i < 16384; i = i + 1) begin
            expected['h12000 + i] = aux_fixture[i];
            if (i % 2 == 0) memory[('h12000 + i) / 2][7:0] = aux_fixture[i];
            else memory[('h12000 + i) / 2][15:8] = aux_fixture[i];
        end
        pause_cycles = int'(cpu_completed);""")
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = host_path.read_text()
    host = once(host, '{0x340000, 0x7880}', '{0x340000, 0x7880}, {0x350000, 0x4080}')
    host = once(host, '            space:write_u8(0x320040 + i, 0)',
                '            space:write_u8(0x320040 + i, 0)\n            space:write_u8(0x350040 + i, 0)')
    host = once(host, '        space:write_u32(world - 0x1222, 0x320040)', """        space:write_u32(world - 0x1226, os.getenv('IIE_BAD_REFRESH') == '1' and 0x350041 or 0x350040)
        space:write_u32(world - 0x1222, 0x320040)""")
    host = once(host, "            if acks == 2 and os.getenv('IIE_BAD_REFRESH') == '1' then\n                local stride = frame_size // 480\n                local address = 0x100000 + 368 * stride + (stride == 320 and 20 or 4)\n                space:write_u8(address, space:read_u8(address) ~ 0x80)\n            end\n", '')
    host = once(host, "                snapshot(prefix .. 'image.bin', 0x320000, 0x4080)",
                "                snapshot(prefix .. 'image.bin', 0x320000, 0x4080)\n                snapshot(prefix .. 'aux.bin', 0x350000, 0x4080)")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', pins_path]
