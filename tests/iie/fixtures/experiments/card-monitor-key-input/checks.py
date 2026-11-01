#!/usr/bin/env python3
"""Check preserved prompt state and the sixth original register exchange."""
import importlib.util
import os
import re
import struct
from prepare import PROMPT, POST, MATCH, WORK, once


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    key = int(os.environ['IIE_KEY'], 16)
    fault = os.environ['IIE_KEY_CONTROL']
    prefix = output[:next((i for i, line in enumerate(output) if line.startswith('KEY arrival')), len(output))]
    post_source = (POST / 'checks.py').read_text()
    post_source = once(post_source, "    source = (MATCH / 'checks.py').read_text()", """    source = (MATCH / 'checks.py').read_text()
    source = source.replace("(run / 'world.bin')", "(run / 'prekey-world.bin')")
    source = source.replace("(run / 'code-after.bin')", "(run / 'prekey-code.bin')")
    start = source.index("        assert (run / 'state.txt').read_text().strip() ==")
    end = source.index('        assert len(transactions)', start)
    source = source[:start] + "        assert (run / 'prekey-state.bin').read_bytes() == struct.pack('>II', 0x20281c, 0x3f0000)\\n" + source[end:]
""")
    source = (PROMPT / 'checks.py').read_text()
    source = once(source, "    source = (POST / 'checks.py').read_text()", '    source = post_source')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('key_prefix_checks', loader=None))
    module.post_source = post_source
    exec(compile(source, str(PROMPT / 'checks.py'), 'exec'), module.__dict__)
    module.check_host(driver, run, snapshots, records[:56], prefix, render, False, transactions[:264])
    print('PASS inherited prompt and cold-start prefix', flush=True)
    key_scan = (run / 'key-instructions.txt').read_text().splitlines()
    key_pcs = [int(line[:4], 16) for line in key_scan]
    delivery = [line for line in output if line.startswith('KEY_DELIVERY')]
    assert delivery == [f'KEY_DELIVERY raw={key:02x} offset=18 width=8 pulses=1 total_pds=281']
    if fault == 'strobe':
        assert not key_scan and any('key strobe creation missing' in line for line in output)
    else:
        for address in (0xc27d, 0xc27f, 0xc28c, 0xc28f, 0xc291, 0xc292, 0xc295, 0xc297, 0xc298, 0xc29b):
            assert key_pcs.count(address) == 1, (hex(address), key_pcs.count(address))
        assert any('KEY_CLEAR completed=1 cursor=a0 stack=ef' in line for line in output)
        assert [line for line in output if line.startswith('KEY_READ')] == [
            f'KEY_READ number=1 data={key | 0x80:02x}', f'KEY_READ number=2 data={key | 0x80:02x}']
    if fault:
        assert len(transactions) == 264 and len(records) == 56
        assert not any(line.startswith('PASS key-input') for line in output)
        if fault == 'clear':
            assert any(f'key clear completion missing latch={key | 0x80:02x}' in line for line in output)
            assert key_scan[-1].startswith('c29b 8d ') and 0xfd78 not in key_pcs
        return
    assert len(transactions) == 314 and len(records) == 67
    saves = [(int(index), int(value, 16)) for index, value in re.findall(
        r'^SAVE register=(\d) value=([0-9a-f]+)$', '\n'.join(output), re.M)]
    assert len(saves) == 30
    before = (run / 'prekey-world.bin').read_bytes()
    world = bytearray(before)
    state = list(before[0x5960 - 0x894:0x5960 - 0x88f])
    position = 56
    for index, value in saves[25:]:
        state[index] = value
        assert records[position][2:4] == [12, 0] and records[position][4:] == state
        position += 1
    assert state == [key | 0x80, 0, 1, 0xa4 if key == 0x15 else 0x25, 0xf1]
    original_p = state[3]
    state[0] = 0x88 if state[0] == 0xff else state[0]
    state[3] = original_p | 2 if key == 0x15 else original_p & 0xfd
    assert records[position][2:4] == [12, 0] and records[position][4:] == state
    position += 1
    for index in (4, 3, 2, 1, 0):
        assert records[position][2:4] == [25, state[index]] and records[position][4:] == state
        position += 1
    assert position == 67
    world[0x5960 - 0x894:0x5960 - 0x88f] = bytes(state)
    world[0x5960 - 0x88f] = 6
    assert (run / 'key-preack-world.bin').read_bytes() == (run / 'world.bin').read_bytes() == world
    assert (run / 'key-preack-code.bin').read_bytes() == (run / 'code-after.bin').read_bytes() == (run / 'prekey-code.bin').read_bytes()
    assert (run / 'key-preack-frame.bin').read_bytes() == (run / 'key-final-frame.bin').read_bytes() == (run / 'match-frame.bin').read_bytes()
    assert (run / 'state.txt').read_text().strip() == 'services=6 returns=30 transactions=314 pc=20281c sp=3f0000'
    for address in (0xfec5, 0xfec8, 0xfd38, 0xfd3c, 0xfd78, 0xd065):
        assert key_pcs.count(address) == 1, (hex(address), key_pcs.count(address))
    assert key_scan[-1].startswith('d065 40 ')
    for address, stack in ((0xc291, 0xec), (0xc292, 0xed), (0xc295, 0xee), (0xc297, 0xee),
                           (0xc298, 0xef), (0xc29b, 0xef), (0xc20a, 0xef), (0xfec5, 0xf0),
                           (0xfec8, 0xf0), (0xfd38, 0xf2), (0xfd3c, 0xf2), (0xfd78, 0xf4)):
        line = next(line for line in key_scan if line.startswith(f'{address:04x} '))
        assert line.endswith(f'S={stack:02x}'), line
    assert key_pcs.count(0xfd7a) == 1 and key_pcs.index(0xfd78) < key_pcs.index(0xfd7a) < key_pcs.index(0xd000)
    assert not any(address in key_pcs for address in (0xfd84, 0xfd47))
    host_pcs = [int(pc, 16) - 0x200000 for pc in re.findall(
        r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
    assert host_pcs.count(0x1f38) == 1
    assert host_pcs.count(0x1f42) == int(key == 0x7f)
    assert host_pcs.count(0x1f48) == int(key != 0x15)
    assert host_pcs.count(0x1f56) == int(key == 0x15)
    assert any('PDS_ACCOUNT prelude=16 guest=314 delivery=1 total=331' in line for line in output)
