#!/usr/bin/env python3
"""Run the original event routine with a modeled event source."""
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
WORK = ROOT / 'local/experiments/card-event-processing'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--event', type=int, choices=(3, 5), default=3)
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
    assert (folder / 'world.bin').read_bytes() == world
    assert (folder / 'state.bin').read_bytes() == struct.pack('>4I', 0x280000, 0x3f0004, 0, 0x300000)
    writes = (folder / 'writes.txt').read_text().splitlines()
    expected = ['00e00018 41000000 ff000000']
    if args.control:
        assert writes != expected and not writes, writes
    else:
        assert writes == expected, writes
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    for pc in (0x2024aa, 0x20250c, 0x20251a, 0x202650, 0x202730, 0x2025a8):
        assert pcs.count(pc) == 1, hex(pc)
    record = {'driver': args.driver, 'event_type': args.event, 'control': args.control, 'writes': writes,
              'result': 'missing card write rejected' if args.control else 'card write observed',
              'inputs_sha256': {str(p): sha(p) for p in (code, ROM, MAME, HERE / 'execute.lua', HERE / 'run.py')}}
    (HERE / f'{"control" if args.control else "results"}-{args.driver}-{args.event}.json').write_text(
        json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS', record['result'])


if __name__ == '__main__':
    main()
