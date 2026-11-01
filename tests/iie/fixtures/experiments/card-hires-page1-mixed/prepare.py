#!/usr/bin/env python3
"""Extend the frozen hires bridge with PAGE1 text fixtures."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-hires-page1-mixed'
PARENT = ROOT / 'fixtures/experiments/card-hires-live-modes'
spec = importlib.util.spec_from_file_location('modes_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, snapshot_inputs = parent.once, parent.sha, parent.snapshot_inputs


def prepare():
    pins_path = PARENT / 'results-6-36.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for path in (PARENT / 'prepare.py', PARENT / 'run.py', PARENT / 'bridge.lua'):
        assert sha(path) == pins[str(path)], path
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = bench.read_text()
    text = text.replace("'h10800 + i", "'h10400 + i").replace("'h800 + i", "'h400 + i")
    marker = '        if (dut.platform.card.card.cpu_memory_wait) $fatal(1, "fixture while CPU memory outstanding");'
    text = once(text, marker, """        for (row = 0; row < 24; row = row + 1)
            for (column = 0; column < 40; column = column + 1) begin
                text_address = (row % 8) * 128 + (row / 8) * 40 + column;
                if (expected['h10400 + text_address] != 0)
                    $fatal(1, "monitor initial auxiliary text mismatch");
            end
""" + marker)
    text = once(text, "expected['h10400 + i] != 0", "expected['h10400 + i] != 8'(i * 53 + (i / 256) * 17 + 127)")
    text = once(text, 'monitor text clear mismatch offset=%h', 'monitor main clear/auxiliary fixture mismatch offset=%h')
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = host_path.read_text()
    host = once(host, """        if os.getenv('IIE_BAD_REFRESH') == '1' then
            space:write_u32(world - 0x1222, 0x320041)
        end
""", '')
    host = once(host, '            if acks >= 1 then', """            if acks == 2 and os.getenv('IIE_BAD_REFRESH') == '1' then
                local stride = frame_size // 480
                local address = 0x100000 + 368 * stride + (stride == 320 and 20 or 4)
                space:write_u8(address, space:read_u8(address) ~ 0x80)
            end
            if acks >= 1 then""")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', pins_path]
