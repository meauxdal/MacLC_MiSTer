#!/usr/bin/env python3
"""Execute original matching BS3 paths with a modeled resource handle."""
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
WORK = ROOT / 'local/experiments/card-boot-service3-resource'
MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshots():
    pins_path = ROOT / 'fixtures/experiments/card-display-init/results.json'
    pins = json.loads(pins_path.read_text())
    for name, digest in pins['inputs_sha256'].items():
        assert sha(Path(name)) == digest, name
    result = {}
    for record in pins['runs']:
        for name in ('world.bin', 'code-after.bin'):
            path = Path(record['run_directory']) / name
            assert sha(path) == record['hashes'][name]
            result[record['driver'], name] = path
    return result, [pins_path, *result.values()]


def frame(driver, source):
    stride = 320 if driver == 5 else 80
    result = bytearray([0x5a]) * (stride * 480 + 128)
    colors = [15, 3, 6, 5, 9, 14, 13, 7, 10, 2, 12, 4, 8, 1, 11, 0]
    mono = [0x3fff, 0x1ddd, 0x2eee, 0x0ccc, 0x3777, 0x1555, 0x2666, 0x0444,
            0x3bbb, 0x2666, 0x2aaa, 0x0888, 0x0ccc, 0x1111, 0x2222, 0]
    cells = [(row, col, (row % 8) * 128 + (row // 8) * 40)
             for row in range(24) for col in range(40)]
    for row, col, offset in cells:
        index = offset + col - 0x200
        if not 0 <= index < len(source): continue
        value = source[index]
        for line in range(16):
            color = (value >> (4 if line >= 8 else 0)) & 15
            for pixel in range(14):
                x = (40 if driver == 5 else 32) + col * 14 + pixel
                y = 48 + row * 16 + line
                if driver == 5:
                    index, shift = 64 + y * stride + x // 2, 4 if x % 2 == 0 else 0
                    result[index] = (result[index] & ~(15 << shift)) | (colors[color] << shift)
                else:
                    index, shift = 64 + y * stride + x // 8, 7 - x % 8
                    result[index] = (result[index] & ~(1 << shift)) | (((mono[color] >> (13 - pixel)) & 1) << shift)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--profile', choices=('normal', 'override', 'special', 'absent'), default='normal')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    assert not args.control or args.profile == 'normal', 'control requires normal profile'
    source = CODE / f'CODE_{args.driver}.bin'
    snap, inputs = snapshots()
    metadata_path = ROOT / 'local/experiments/firmware-memory/resources.json'
    metadata = json.loads(metadata_path.read_text())
    fork = ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc'
    assert sha(fork) == metadata['sha256']
    entry = next(r for r in metadata['resources'] if (r['type'], r['id']) == ('STR ', 0x5101))
    resource = fork.read_bytes()[entry['fork_offset']:entry['fork_offset'] + entry['size']]
    assert len(resource) == 77 and resource[0] == 76 and hashlib.sha256(resource).hexdigest() == entry['sha256']
    WORK.mkdir(parents=True, exist_ok=True)
    payload = WORK / 'str5101.bin'; payload.write_bytes(resource)
    run = WORK / f'{args.driver}-{args.profile}-{int(args.control)}-{time.time_ns()}'
    run.mkdir()
    env = dict(os.environ, IIE_BS3_RUN=run.as_posix(), IIE_BS3_CODE=source.as_posix(),
               IIE_BS3_PROFILE=args.profile, IIE_BS3_FAULT=str(int(args.control)),
               IIE_BS3_RESOURCE=payload.as_posix(), IIE_FRAME_SIZE=str((320 if args.driver == 5 else 80) * 480),
               IIE_INIT_CODE=snap[args.driver, 'code-after.bin'].as_posix(),
               IIE_INIT_WORLD=snap[args.driver, 'world.bin'].as_posix())
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51', '-skip_gameinfo',
        '-cfg_directory', str(run / 'cfg'), '-nvram_directory', str(run / 'nvram'), '-noreadconfig',
        '-nowriteconfig', '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0',
        '-debug', '-debugger', 'none', '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    execution = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    (run / 'mame.log').write_text(execution.stdout + execution.stderr, encoding='ascii')
    assert execution.returncode == 0 and '[LUA ERROR]' not in execution.stdout + execution.stderr
    world = bytearray((run / 'before-world.bin').read_bytes())
    before = bytearray(snap[args.driver, 'world.bin'].read_bytes())
    before[0x5960 - 0x1236:0x5960 - 0x1232] = (0xe00000).to_bytes(4, 'big')
    before[0x5960 - 0x5814] = 0xa5 if args.profile == 'override' else 0
    before[0x5960 - 0x86c:0x5960 - 0x86a] = (0xa5b1 if args.profile == 'special' else 0xa5b6).to_bytes(2, 'big')
    before[0x5960 - 0x894] = 0xc0 if args.profile == 'special' else 0xc4
    before[0x5960 - 0x891] = 0xa5
    before[0x5960 - 0x97c:0x5960 - 0x97a] = bytes.fromhex('5a5a')
    assert world == before
    if args.profile == 'override': world[0x5960 - 0x5814] = 0
    if not args.control: world[0x5960 - 0x891] |= 2
    rendered = args.profile in ('normal', 'override')
    chars = bytes(value | 0x80 for value in resource[1:])
    if rendered:
        world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
        offset = 0x5960 - 0x4412
        world[offset:offset + len(chars) * 2] = bytes(v for item in chars for v in (1, item))
        for index in range(76): world[0x5960 - 0x4412 + index * 2] = 0
    actual = (run / 'world.bin').read_bytes()
    assert actual == world, [(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual, world)) if a != b][:15]
    assert (run / 'loaded.bin').read_bytes() == source.read_bytes()
    assert (run / 'before-code.bin').read_bytes() == snap[args.driver, 'code-after.bin'].read_bytes()
    assert (run / 'code-after.bin').read_bytes() == (run / 'before-code.bin').read_bytes()
    assert (run / 'frame.bin').read_bytes() == frame(args.driver, chars if rendered else b'')
    expected_resource = bytearray([0x5a]) * 206
    expected_resource[64:141] = resource
    if rendered:
        expected_resource[65:141] = chars
        expected_resource[141] |= 0x80
    assert (run / 'resource-after.bin').read_bytes() == expected_resource
    traps = 1 if rendered else 0
    assert (run / 'reads.txt').read_text().splitlines() == ['21 20'] * (4 if rendered else 0)
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
    assert pcs.count(0x201d8a) == 1 and pcs.count(0x201df6) == (77 if rendered else 0)
    assert pcs.count(0x20057e) == traps
    gets = int(args.profile != 'special')
    assert (run / 'state.bin').read_bytes() == struct.pack('>6I', 0x280000, 0x3f0004, 0x300000, gets, traps, traps)
    if gets:
        assert (run / 'resource-stack.bin').read_bytes()[:6] == struct.pack('>HI', 0x5101, 0x53545220)
    if rendered:
        assert (run / 'lock.bin').read_bytes() == (run / 'unlock.bin').read_bytes() == struct.pack('>I', 0x360000)
    if args.control:
        assert (run / 'fault-pc.bin').read_bytes() == bytes.fromhex('00201e0c00201e12')
        assert (run / 'fault-before.bin').read_bytes() == (run / 'fault-after.bin').read_bytes()
        assert actual[0x5960 - 0x891] == 0xa5
    inputs += [source, ROM, MAME, fork, metadata_path, payload, HERE / 'run.py', HERE / 'execute.lua']
    record = {'driver': args.driver, 'profile': args.profile, 'control': args.control,
              'scope': 'direct original BS3 with initializer snapshots and modeled resource traps',
              'run_directory': str(run), 'rendered_cells': 76 if rendered else 0,
              'saved_p': actual[0x5960 - 0x891], 'resource_transform_bytes': 77 if rendered else 0,
              'inputs_sha256': {str(p): sha(p) for p in inputs},
              'captures_sha256': {p.name: sha(p) for p in run.iterdir() if p.is_file()}}
    name = f'{"control" if args.control else "results"}-{args.driver}-{args.profile}.json'
    (HERE / name).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS original BS3', args.driver, args.profile, 'control' if args.control else 'positive')


if __name__ == '__main__':
    main()
