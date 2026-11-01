#!/usr/bin/env python3
"""Bind modeled glyphs and original lookup generation to the PAGE2 bridge."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-text'
PARENT = ROOT / 'fixtures/experiments/card-display-page2'
spec = importlib.util.spec_from_file_location('page_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha
FIRST_ACK, LAST_ACK = 1046, 1053


def snapshot_inputs():
    snapshots, inputs = parent.snapshot_inputs()
    results_path = ROOT / 'fixtures/experiments/card-display-glyph/results.json'
    results = json.loads(results_path.read_text())
    for name, digest in results['inputs_sha256'].items():
        assert sha(Path(name)) == digest, 'changed glyph source: ' + name
    run = next(r for r in results['runs'] if not r['control'])
    for name in ('world.bin', 'font.bin'):
        path = Path(run['run_directory']) / name
        assert sha(path) == run['hashes'][name]
        snapshots['card-display-glyph', 0, name] = path
        inputs.append(path)
    return snapshots, inputs + [results_path]


def prepare():
    pins_path = PARENT / 'results-5.json'
    assert sha(PARENT / 'prepare.py') == json.loads(pins_path.read_text())['inputs_sha256'][str(PARENT / 'prepare.py')]
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    _, snapshot_paths = snapshot_inputs()
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index <= 1048;', f'bridge_index <= {FIRST_ACK};')
    text = once(text, 'bridge_index = 1049; bridge_index <= 1055;',
                f'bridge_index = {FIRST_ACK + 1}; bridge_index <= {LAST_ACK};')
    text = once(text, 'bridge_index <= 13 &&', 'bridge_index <= 11 &&')
    text = once(text, 'bridge_index == 14 &&', 'bridge_index == 12 &&')
    text = once(text, "8'(i * 37 + (i / 16) * 11 + 61)", "8'(i * 37 + (i / 256) * 11 + 61)")
    text = once(text, 'transact(0, 0, 33, (mask_seed & 3) | 48, 0);',
                'transact(0, 0, 33, (mask_seed & 3) | 16, 0);')
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), "dofile('fixtures/experiments/card-display-page2/bridge.lua')",
                "dofile('fixtures/experiments/card-display-text/bridge.lua')")
    host = once(host, 'space:write_u16(world - 0x972, 2)', 'space:write_u16(world - 0x972, 0x42)')
    host = once(host, "        overlay(assert(os.getenv('IIE_INIT_CODE')), base)", """        overlay(assert(os.getenv('IIE_INIT_CODE')), base)
        overlay(assert(os.getenv('IIE_MAIN_CODE')), 0x280000)
        local glyph_file = assert(io.open(assert(os.getenv('IIE_GLYPH_WORLD')), 'rb'))
        glyph_file:seek('set', 0x5960 - 0x2412)
        local glyphs = glyph_file:read(4096)
        glyph_file:close()
        assert(#glyphs == 4096)
        for i = 1, #glyphs do space:write_u8(world - 0x2412 + i - 1, glyphs:byte(i)) end
        if os.getenv('IIE_BAD_GLYPH') == '1' then
            local address = world - 0x2412 + 0x40 * 16
            space:write_u16(address, space:read_u16(address) ~ 4)
        end""")
    host = once(host, "snapshot(acks == 1 and 'mode-code.bin' or 'code-after.bin', base, #bytes)",
                "snapshot(acks == 1 and 'mode-code.bin' or 'code-after.bin', base, #bytes)\n                snapshot('main-after.bin', 0x280000, 0x685c)")
    host = once(host, "        cpu.state['PC'].value = base + 0x2c4", """        space:write_u32(0x3efff8, base + 0x2c4)
        cpu.state['A7'].value = 0x3efff8
        cpu.state['PC'].value = 0x284300""")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'bridge.lua',
        PARENT / 'prepare.py', pins_path, *snapshot_paths]
