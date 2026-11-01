#!/usr/bin/env python3
"""Check original poll and display path captures."""
import re
import struct
import os
from prepare import ROOT, WORK, text_oracle


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    assert (run / 'render-state.bin').read_bytes() == struct.pack('>II', 0x202836, 0x3f0000)
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
    for pc in (0x20281c, 0x20135e, 0x201a0e, 0x2016d8, 0x2007ae, 0x20081a):
        assert pc in pcs, hex(pc)
    fault = os.environ['IIE_POLL_CONTROL']
    if fault == 'pause':
        assert any('runtime hold blocked pending response' in line for line in output)
        assert not any(line.startswith('PASS poll-display') for line in output)
        return 'runtime hold blocked pending response'
    assert any(line.startswith('PASS poll-display') for line in output)
    assert len((run / 'live-page.bin').read_bytes()) == 1024
    assert (run / 'render-code.bin').read_bytes() == (run / 'code-after.bin').read_bytes()
    assert (run / 'render-main.bin').read_bytes() == (render.CODE / 'CODE_1.bin').read_bytes()
    oracle, _ = text_oracle()
    page = bytearray((run / 'live-page.bin').read_bytes())
    original = (render.CODE / f'CODE_{driver}.bin').read_bytes()
    page[0x250:0x2f8] = bytes(value | 128 for value in original[0x1e14:0x1ebc])
    resource = (WORK / 'str5101.bin').read_bytes()
    page[0x200:0x200 + resource[0]] = bytes(value | 128 for value in resource[1:])
    expected = oracle['expected_frame'](driver, page)
    if fault == 'status':
        assert (run / 'render-frame.bin').read_bytes() != expected
        return 'live prompt pixel mismatch'
    assert (run / 'render-frame.bin').read_bytes() == expected, 'live prompt pixel mismatch'
    assert sum(line.startswith('PAUSE_PENDING') for line in output) == 2
    world = (run / 'render-world.bin').read_bytes()
    cache = world[0x5960 - 0x4812:0x5960 - 0x4012]
    assert cache[1::2] == page, 'live text cache mismatch'
    for _, _, address in oracle['visible_cells']():
        assert cache[(address - 0x400) * 2] == 0
    assert world[0x5960 - 0x2412:0x5960 - 0x1412] == oracle['glyph_state']()
    assert world[0x5960 - 0x972:0x5960 - 0x970] == bytes.fromhex('0050')
    assert world[0x5960 - 0x974] == 0x40
