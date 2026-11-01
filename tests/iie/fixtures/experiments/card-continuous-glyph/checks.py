#!/usr/bin/env python3
"""Check uninterrupted glyph storage through live prompt rendering."""
import re
import struct
from prepare import ROOT, WORK, text_oracle


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    base, main, world, frame, stack = struct.unpack('>5I', (run / 'context.bin').read_bytes())
    assert (run / 'render-state.bin').read_bytes() == struct.pack('>II', base + 0x2836, stack)
    original = (render.CODE / 'CODE_2.bin').read_bytes()
    assert (run / 'glyph-code-before.bin').read_bytes() == original
    assert (run / 'glyph-code-after.bin').read_bytes() == original
    oracle, _ = text_oracle()
    glyph = oracle['glyph_state']()
    assert (run / 'glyph-live.bin').read_bytes() == glyph
    state = (run / 'render-world.bin').read_bytes()
    assert state[0x5960 - 0x2412:0x5960 - 0x1412] == glyph
    page = bytearray((run / 'live-page.bin').read_bytes())
    original = (render.CODE / f'CODE_{driver}.bin').read_bytes()
    page[0x250:0x2f8] = bytes(value | 128 for value in original[0x1e14:0x1ebc])
    resource = (WORK / 'str5101.bin').read_bytes()
    page[0x200:0x200 + resource[0]] = bytes(value | 128 for value in resource[1:])
    assert state[0x5960 - 0x4812:0x5960 - 0x4012][1::2] == page
    assert (run / 'render-frame.bin').read_bytes() == oracle['expected_frame'](driver, page)
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
    for offset in (0x4e, 0x7ae, 0x81a, 0x281c, 0x135e, 0x1a0e):
        assert base + offset in pcs
    assert main + 0x4300 in pcs
    assert any(line.startswith('PASS poll-display') for line in output)
