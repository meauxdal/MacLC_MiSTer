#!/usr/bin/env python3
"""Independent host-world, resource, pixel and return checks."""
import os
import re
import struct
from prepare import WORK


def expected_frame(driver, render, banner, resource):
    stride = 320 if driver == 5 else 80
    result = bytearray([0x5a]) * (stride * 480 + 128)
    cells = 0
    for row, col, address in render.visible_cells():
        if 0x600 <= address < 0x600 + len(resource):
            value = resource[address - 0x600]
        elif 0x650 <= address < 0x6f8:
            value = banner[address - 0x650]
        else:
            continue
        cells += 1
        for line in range(16):
            color = (value >> (4 if line >= 8 else 0)) & 15
            for pixel in range(14):
                x = (40 if driver == 5 else 32) + col * 14 + pixel
                y = 48 + row * 16 + line
                if driver == 5:
                    index, shift = 64 + y * stride + x // 2, 4 if x % 2 == 0 else 0
                    result[index] = (result[index] & ~(15 << shift)) | (render.COLORS[color] << shift)
                else:
                    index, shift = 64 + y * stride + x // 8, 7 - x % 8
                    result[index] = (result[index] & ~(1 << shift)) | (((render.MONO[color] >> (13 - pixel)) & 1) << shift)
    assert cells == 236
    return result


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    profile = os.environ['IIE_BOOT_PROFILE']
    flag, config = (0xa5, 0xa5b1) if profile == 'override' else (0, 0xa5b6)
    original = (render.CODE / f'CODE_{driver}.bin').read_bytes()
    banner = bytes(value | 0x80 for value in original[0x1e14:0x1ebc])
    resource = (WORK / 'str5101.bin').read_bytes()
    chars = bytes(value | 0x80 for value in resource[1:])
    assert (run / 'frame.bin').read_bytes() == render.expected_frame(driver, banner)
    assert (run / 'match-frame.bin').read_bytes() == expected_frame(driver, render, banner, chars)
    assert (run / 'boot-profile.bin').read_bytes() == bytes([flag]) + config.to_bytes(2, 'big')
    world = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    world[0x5960 - 0x5814] = flag
    world[0x5960 - 0x86c:0x5960 - 0x86a] = config.to_bytes(2, 'big')
    world[0x5960 - 0x1236:0x5960 - 0x1232] = (0xe00000).to_bytes(4, 'big')
    world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
    world[0x5960 - 0x4372:0x5960 - 0x4372 + len(banner) * 2] = \
        bytes(value for item in banner for value in (1, item))
    for _, _, address in render.visible_cells():
        if 0x650 <= address < 0x6f8:
            world[0x5960 - 0x4812 + (address - 0x400) * 2] = 0
    saves = [(int(index), int(value, 16)) for index, value in re.findall(
        r'^SAVE register=(\d) value=([0-9a-f]+)$', '\n'.join(output), re.M)]
    assert len(saves) == 25 and len(records) == (51 if control else 55)
    state = list(snapshots['card-display-init', driver, 'world.bin'].read_bytes()[
        0x5960 - 0x894:0x5960 - 0x88f])
    position = 0
    for service in range(5):
        for index, value in saves[service * 5:service * 5 + 5]:
            state[index] = value
            assert records[position][2:4] == [12, 0] and records[position][4:] == state
            position += 1
        if service == 1:
            state[2] = 9
        elif service == 2:
            state[0] = 0xc6
        elif service == 3:
            assert state[0] == 0xc5 and state[2] == 5 and state[3] & 2 == 0
            state[3] &= 0xfd
        elif service == 4:
            assert state[0] == 0xc4 and state[2] == 5 and state[3] & 2 == 0
            if not control:
                state[3] |= 2
            world[0x5960 - 0x5814] = 0
            offset = 0x5960 - 0x4412
            world[offset:offset + len(chars) * 2] = bytes(v for item in chars for v in (0, item))
        assert records[position][2:4] == [12, 0] and records[position][4:] == state
        position += 1
        world[0x5960 - 0x894:0x5960 - 0x88f] = bytes(state)
        world[0x5960 - 0x88f] = (1, 4, 2, 3, 3)[service]
        name = (None, 'service4-world.bin', 'boot-preack-world.bin',
                'bs3-preack-world.bin', 'match-world.bin')[service]
        if name:
            assert (run / name).read_bytes() == world, name
        for index in ((4,) if control and service == 4 else (4, 3, 2, 1, 0)):
            assert records[position][2:4] == [25, state[index]] and records[position][4:] == state
            position += 1
    assert position == len(records)
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    code[0x1e14:0x1ebc] = banner
    for name in ('service4-code.bin', 'boot-preack-code.bin', 'bs3-preack-code.bin', 'match-code.bin'):
        assert (run / name).read_bytes() == code, name
    assert (run / 'loaded.bin').read_bytes() == original
    guarded = bytearray([0x5a]) * 206
    guarded[64:141] = resource
    guarded[65:141] = chars
    guarded[141] |= 0x80
    assert (run / 'resource-after.bin').read_bytes() == guarded
    assert (run / 'resource-stack.bin').read_bytes()[:6] == struct.pack('>HI', 0x5101, 0x53545220)
    assert (run / 'lock.bin').read_bytes() == (run / 'unlock.bin').read_bytes() == struct.pack('>I', 0x360000)
    assert (run / 'resource-traps.bin').read_bytes() == struct.pack('>III', 1, 1, 1)
    pcs = [int(pc, 16) - 0x200000 for pc in re.findall(
        r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
    assert pcs.count(0x1d8a) == 2 and pcs.count(0x1df6) == 77
    assert pcs.count(0x057e) == 2 and pcs.count(0x1db8) == 1
    assert pcs.count(0x1d9a) == int(profile == 'override')
    assert [value for write, width, off, value in transactions if not write and off == 33] == [0xfc] + [0x20] * 8
    if control:
        assert (run / 'fault-pc.bin').read_bytes() == bytes.fromhex('00201e0c00201e12')
        assert (run / 'fault-before.bin').read_bytes() == (run / 'fault-after.bin').read_bytes() == world
    else:
        assert (run / 'world.bin').read_bytes() == world
        assert (run / 'code-after.bin').read_bytes() == code
        assert (run / 'state.txt').read_text().strip() == \
            'services=5 returns=25 transactions=260 pc=20281c sp=3f0000'
        assert len(transactions) == 260
        scan = (run / 'instructions.txt').read_text().splitlines()
        probes = [line for line in scan if line.startswith('fac7 ')]
        assert len(probes) == 1 and 'Y=05' in probes[0]
        assert scan[-1].startswith('fac2 f0 A=c4 ')
        assert any('EXTERNAL address=c505 physical=2c505 data=ea' in line for line in output)
        assert any('SCAN next_A=c4 next_PC=fa9b external_reads=1' in line for line in output)
