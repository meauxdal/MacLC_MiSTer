#!/usr/bin/env python3
"""Extend the text bridge to paired main/aux reads and character selectors."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-text80'
PARENT = ROOT / 'fixtures/experiments/card-display-text'
spec = importlib.util.spec_from_file_location('text_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, snapshot_inputs = parent.once, parent.sha, parent.snapshot_inputs
FIRST_ACK, LAST_ACK = parent.FIRST_ACK, parent.LAST_ACK


def prepare():
    pins_path = PARENT / 'results-5.json'
    assert sha(PARENT / 'prepare.py') == json.loads(pins_path.read_text())['inputs_sha256'][str(PARENT / 'prepare.py')]
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), "            expected['h800 + i] =", """            expected['h10800 + i] = 8'(i * 53 + (i / 256) * 17 + 127);
            if (i % 2 == 0) memory[('h10800 + i) / 2][7:0] = expected['h10800 + i];
            else memory[('h10800 + i) / 2][15:8] = expected['h10800 + i];
            expected['h800 + i] =""")
    text = once(text, 'transact(0, 0, 33, (mask_seed & 3) | 16, 0);',
                'transact(0, 0, 33, (mask_seed & 3) | 24, 0);')
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), "dofile('fixtures/experiments/card-display-text/bridge.lua')",
                "dofile('fixtures/experiments/card-display-text80/bridge.lua')")
    host = once(host, 'space:write_u16(world - 0x972, 0x42)',
                """space:write_u16(world - 0x972, tonumber(assert(os.getenv('IIE_TEXT_MODE'))))
        space:write_u8(world - 0x970, tonumber(assert(os.getenv('IIE_GLYPH_BANK'))))""")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'bridge.lua', PARENT / 'prepare.py', pins_path]
