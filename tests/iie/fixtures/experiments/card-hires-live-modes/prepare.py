#!/usr/bin/env python3
"""Extend the checked live hires bridge without changing its frozen sources."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-hires-live-modes'
PARENT = ROOT / 'fixtures/experiments/card-hires-refresh'
spec = importlib.util.spec_from_file_location('hires_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, snapshot_inputs = parent.once, parent.sha, parent.snapshot_inputs


def prepare():
    pins_path = PARENT / 'results-22.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    assert sha(PARENT / 'prepare.py') == pins[str(PARENT / 'prepare.py')]
    parent.WORK = WORK
    sources, image, inputs = parent.prepare(1)
    bench = sources[0]
    text = once(bench.read_text(), 'parameter FAST = 0, BAD_PAUSE = 0',
                'parameter FAST = 0, BAD_PAUSE = 0, FIRST_ACK = 8214, LAST_ACK = 8223, HIRES_MASK = 64')
    text = once(text, 'bridge_index <= 8214;', 'bridge_index <= FIRST_ACK;')
    text = once(text, 'bridge_index = 8215; bridge_index <= 8223;',
                'bridge_index = FIRST_ACK + 1; bridge_index <= LAST_ACK;')
    text = once(text, 'transact(0, 0, 33, (mask_seed & 3) | 64, 0);',
                'transact(0, 0, 33, (mask_seed & 3) | HIRES_MASK, 0);')
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), "dofile('fixtures/experiments/card-hires-refresh/bridge.lua')",
                "dofile('fixtures/experiments/card-hires-live-modes/bridge.lua')")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'bridge.lua', PARENT / 'prepare.py', pins_path]
