#!/usr/bin/env python3
"""Check original non-keyboard event handler dispatch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'
MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
WORK = ROOT / 'local/experiments/card-event-paths'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--event', type=int, choices=(1, 2, 11), default=1)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    code = CODE / f'CODE_{args.driver}.bin'
    folder = WORK / f'{args.driver}-{args.event}-{int(args.control)}-{time.time_ns()}'
    folder.mkdir(parents=True)
    env = dict(os.environ, IIE_EVENT_RUN=folder.as_posix(), IIE_EVENT_CODE=code.as_posix(),
               IIE_EVENT_FAULT=str(int(args.control)), IIE_EVENT_TYPE=str(args.event))
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
        '-skip_gameinfo', '-cfg_directory', str(folder / 'cfg'), '-nvram_directory', str(folder / 'nvram'),
        '-snapshot_directory', str(folder / 'snap'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
        '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    (folder / 'mame.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    assert result.returncode == 0 and '[LUA ERROR]' not in result.stdout + result.stderr
    assert (folder / 'code.bin').read_bytes() == code.read_bytes()
    assert (folder / 'trap.bin').read_bytes() == struct.pack('>2I', 0xfff7, 0x2ff720)
    world = bytearray(0x5c49)
    world[0x5960 - 0x1236:0x5960 - 0x1232] = bytes.fromhex('00e00000')
    world[0x5960 - 0x8e0:0x5960 - 0x8d0] = struct.pack('>HIIIH', args.event, 0xff41, 0x12345678, 0x00020003, 0)
    world[0x5960 - 0x1394:0x5960 - 0x1392] = struct.pack('>H', 1 << ((args.event + 1) % 16))
    for index, slot in enumerate((20, 7, 0)):
        for offset, value, form in ((-0x1396 + slot * 2, 1 << args.event, '>H'),
                (-0x13ea + slot * 4, 0x320000 + index * 0x100, '>I'),
                (-0x140a + slot * 4, 0x330000 + slot * 0x100, '>I')):
            payload = struct.pack(form, value)
            world[0x5960 + offset:0x5960 + offset + len(payload)] = payload
    world[0x5960 - 0x106e:0x5960 - 0x106c] = b'\x00\x01'
    assert (folder / 'world.bin').read_bytes() == world
    assert (folder / 'state.bin').read_bytes() == struct.pack('>4I', 0x280000, 0x3f0004, 0, 0x300000)
    writes = (folder / 'writes.txt').read_text().splitlines()
    assert writes == ['00e00020 00000000 ff000000', '00e0000c 00000000 00ff0000'], writes
    handlers = bytearray(0x300)
    for index in range(3):
        handlers[index * 0x100 + 0x1c:index * 0x100 + 0x22] = bytes.fromhex('70ff76ff4e75')
    assert (folder / 'handlers.bin').read_bytes() == handlers
    calls = []
    for index, slot in enumerate((20, 7, 0)):
        path = folder / f'handler-{slot}.bin'
        if args.control and slot == 7:
            assert not path.exists()
            continue
        values = struct.unpack('>7I', path.read_bytes())
        assert values[:6] == (args.event, (0xc0 | slot) << 8, slot,
            0x320000 + index * 0x100, 0x2ff720, 0x330000 + slot * 0x100), values
        assert values[6] == 0x3efff4, values
        calls.append({'slot': slot, 'registers': list(values)})
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    for pc in (0x2024aa, 0x20250c, 0x20251a, 0x2025ac, 0x2025f4, 0x2025a8):
        assert pcs.count(pc) == 1, hex(pc)
    assert pcs.count(0x2025ae) == 24
    observed_order = [slot for pc in pcs for index, slot in enumerate((20, 7, 0))
                      if pc == 0x32001c + index * 0x100]
    assert observed_order == ([20, 0] if args.control else [20, 7, 0]), observed_order
    record = {'driver': args.driver, 'event_type': args.event, 'control': args.control, 'writes': writes,
              'calls': calls, 'dispatch_order': observed_order,
              'result': 'missing handler rejected' if args.control else 'handler dispatch observed',
              'inputs_sha256': {str(p): sha(p) for p in (code, ROM, MAME, HERE / 'execute.lua', HERE / 'run.py',
                  ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')},
              'captures_sha256': {p.name: sha(p) for p in sorted(folder.glob('*.bin'))}}
    (HERE / f'{"control" if args.control else "results"}-{args.driver}-{args.event}.json').write_text(
        json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS', record['result'])


if __name__ == '__main__':
    main()
