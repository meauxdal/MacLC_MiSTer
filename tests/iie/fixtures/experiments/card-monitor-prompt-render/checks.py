#!/usr/bin/env python3
"""Check the preserved echo checkpoint and original prompt pixels."""
import importlib.util
import os
import re
import struct
from prepare import ECHO, KEY, once, text_oracle


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    source = (KEY / 'checks.py').read_text()
    source = once(source, "assert (run / 'state.txt').read_text().strip() == 'services=6 returns=30 transactions=314 pc=20281c sp=3f0000'",
                  "assert (run / 'prefix-state.bin').read_bytes() == struct.pack('>II', 0x20281c, 0x3f0000)")
    key_module = importlib.util.module_from_spec(importlib.util.spec_from_loader('render_key_checks', loader=None))
    exec(compile(source, str(KEY / 'checks.py'), 'exec'), key_module.__dict__)
    spec = importlib.util.spec_from_file_location('render_echo_checks', ECHO / 'checks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.parent = key_module
    source = (ECHO / 'checks.py').read_text()
    start = source.index('def check_host(')
    source = source[start:].replace('PASS key-echo fast=', 'PASS prompt-render fast=')
    exec(compile(source, str(ECHO / 'checks.py'), 'exec'), module.__dict__)
    module.check_host(driver, run, snapshots, records[:67], output, render, control, transactions[:314])
    oracle, _ = text_oracle()
    page = (run / 'live-page.bin').read_bytes()
    assert len(page) == 1024
    key = int(os.environ['IIE_KEY'], 16)
    fault = os.environ['IIE_RENDER_CONTROL']
    visible = bytearray([0xa0]) * 1024
    visible[15:24] = bytes(value | 128 for value in b'Apple //e')
    visible[0x100] = 0xdd
    if key == 0x7f:
        visible[0x180:0x182] = bytes.fromhex('dd60')
    else:
        visible[0x101:0x103] = bytes([0xa0 if key == 0x15 else 0xc1, 0x60])
    for _, _, address in oracle['visible_cells']():
        assert page[address - 0x400] == visible[address - 0x400], hex(address)
    assert page[0x3f8] == 0x31
    expected_transactions = [[False, 8, 32, 136], [True, 8, 32, 128],
        [False, 8, 1, 0], [False, 8, 1, 0], [False, 8, 33, 32], [False, 8, 33, 32],
        [False, 8, 13, 3], [True, 8, 33, 32], [False, 8, 32, 128], [True, 8, 32, 136],
        [False, 8, 32, 136], [True, 8, 12, 0], [False, 8, 13, 3], [True, 8, 13, 3],
        [False, 8, 8, 0], [True, 16, 28, 0x400]]
    expected_transactions += [[False, 8, 16, value] for value in page]
    assert transactions[314:] == expected_transactions and len(transactions) == 1354
    assert len(records) == 68 and records[-1][:4] == [327, 0x2008f2, 12, 0]
    assert records[-1][4:] == records[-2][4:]
    assert any(line == 'RENDER_ACK empty=1 CPU=' + str(33072 if key == 0x7f else 32699 if key == 0x15 else 32687) + ' captures=73' for line in output)
    assert [line for line in output if line.startswith('RENDER_ACCOUNT')] == [
        'RENDER_ACCOUNT guest=1354 delivery=1 prelude=16 protocol=1355 total=1371']
    world = bytearray((run / 'world.bin').read_bytes())
    short, wide = oracle['lookup_tables']()
    world[0x5960 - 0x2812:0x5960 - 0x2412] = short
    world[0x5960 - 0x3812:0x5960 - 0x3012] = wide
    glyph = bytearray(oracle['glyph_state']())
    if fault == 'glyph': glyph[0x41 * 16 + 1] ^= 4
    world[0x5960 - 0x2412:0x5960 - 0x1412] = glyph
    world[0x5960 - 0x971] = world[0x5960 - 0x974] = 0x40
    pairs = bytes(item for value in page for item in (1, value))
    world[0x5960 - 0x4812:0x5960 - 0x4012] = pairs
    for _, _, address in oracle['visible_cells']():
        world[0x5960 - 0x4812 + (address - 0x400) * 2] = 0
    if fault == 'destination':
        start = 0x5960 - 0x85e
        world[start:start + 4] = (int.from_bytes(world[start:start + 4], 'big') + 1).to_bytes(4, 'big')
    actual_world = (run / 'render-world.bin').read_bytes()
    assert actual_world == world, 'render host world mismatch: ' + str([
        (hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
    assert (run / 'render-code.bin').read_bytes() == (run / 'code-after.bin').read_bytes()
    assert (run / 'render-main.bin').read_bytes() == (render.CODE / 'CODE_1.bin').read_bytes()
    assert (run / 'render-state.bin').read_bytes() == struct.pack('>II', 0x290000, 0x3f0000)
    assert (run / 'state.txt').read_text().strip() == 'services=6 returns=30 transactions=1355 pc=290000 sp=3f0000'
    pcs = [int(pc, 16) - 0x200000 for pc in re.findall(r'^([0-9A-F]{8}):', (run / 'render-trace.txt').read_text(), re.M)]
    assert pcs[0] in (0x84300, 0x84304) and pcs[-1] == 0x90000
    for address in (0x8430e, 0x84314, 0x84360, 0x8436a): assert pcs.count(address) == 128
    for address in (0x7ae, 0x81a, 0x8ee, 0xa7e): assert pcs.count(address) == 1
    assert pcs.count(0x9a4) == 1024 and pcs.count(0x9cc) == 0
    assert pcs.count(0x4204 if driver == 5 else 0x3fea) == 960
    assert pcs.count(0x3fa4 if driver == 5 else 0x3eb4) == 960
    expected = oracle['expected_frame'](driver, page)
    actual = (run / 'render-frame.bin').read_bytes()
    if fault:
        assert actual != expected, 'prompt pixel control escaped'
        print('PASS rejected prompt pixel or framebuffer guard mismatch', flush=True)
        return 'prompt pixel or framebuffer guard mismatch'
    assert actual == expected, 'prompt pixel or framebuffer guard mismatch'
    print('PASS original prompt pixels, whole host world and preserved echo prefix', flush=True)
