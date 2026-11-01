#!/usr/bin/env python3
"""Check repeated original glyph-bank settings loads with retained display state."""
import argparse
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-glyph-bank-reload'
TEXT = ROOT / 'fixtures/experiments/card-display-text80'
sys.path.insert(0, str(TEXT))
spec = importlib.util.spec_from_file_location('text_oracle', TEXT / 'run.py')
text = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text)
COLOR = ROOT / 'fixtures/experiments/card-hires-color'
sys.path.insert(0, str(COLOR))
spec = importlib.util.spec_from_file_location('world_oracle', COLOR / 'run.py')
color = importlib.util.module_from_spec(spec)
spec.loader.exec_module(color)
sha, CODE, ROM, MAME = text.sha, text.CODE, text.ROM, text.MAME


def execute(driver, alternate, direct):
    mode = 0xca if alternate else 0x4a
    snapshots, inputs = text.snapshot_inputs()
    folder = WORK / f'{driver}-{mode:02x}-{int(direct)}-{time.time_ns()}'
    folder.mkdir(parents=True)
    initial = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    glyphs = snapshots['card-display-glyph', 0, 'world.bin'].read_bytes()
    initial[0x5960 - 0x2412:0x5960 - 0x1412] = glyphs[0x5960 - 0x2412:0x5960 - 0x1412]
    def put(offset, value, size=4):
        initial[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    put(-0x1104, 2, 2)
    put(-0x1146, 0x50005100)
    put(-0x11c6, 0x360000)
    put(-0x11c2, 0x360004)
    put(-0x1236, 0xe00000)
    put(-0x122a, 0x370040)
    put(-0x972, mode, 2)
    put(-0x974, mode, 1)
    put(-0x96e, int(alternate), 1)
    put(-0x970, 0x55aa, 2)
    for auxiliary, offset in ((False, -0x4012), (True, -0x5012)):
        pairs = bytes(value for item in text.page_data(auxiliary) for value in (1, item))
        initial[0x5960 + offset:0x5960 + offset + len(pairs)] = pairs
    settings = bytearray((i * 17 + 9) & 255 for i in range(32))
    settings[4:6] = bytes(2)
    settings[6:8] = bytes(2)
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    assert code[0x40e:0x414] == bytes.fromhex('08ed0007f690')
    files = {'world-input.bin': initial, 'code-input.bin': code, 'settings.bin': settings}
    for name, contents in files.items():
        (folder / name).write_bytes(contents)
    env = dict(os.environ, IIE_BANK_RUN=folder.as_posix(), IIE_BANK_DRIVER=str(driver),
        IIE_MAIN_CODE=(CODE / 'CODE_1.bin').as_posix(), IIE_BANK_DIRECT=str(int(direct)))
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51', '-skip_gameinfo',
        '-cfg_directory', str(folder / 'cfg'), '-nvram_directory', str(folder / 'nvram'),
        '-snapshot_directory', str(folder / 'snap'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
        '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    with (folder / 'mame.log').open('w') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            assert process.wait(timeout=15) == 0
            shutdown = 'exited_zero'
        except subprocess.TimeoutExpired:
            shutdown = 'timeout_after_guest_return'
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    assert '[LUA ERROR]' not in (folder / 'mame.log').read_text()
    world = bytearray(initial)
    frames = []
    for phase, value in enumerate((0, 1, 0)):
        settings[6:8] = value.to_bytes(2, 'big')
        assert (folder / f'{phase}-settings-after.bin').read_bytes() == settings
        world[0x5960 - 0x886:0x5960 - 0x866] = settings
        def expected_put(offset, value, size=4):
            world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
        expected_put(-0x862, 0x300000 - 0x11c2)
        expected_put(-0x866, 0x300000 - 0x11c6)
        expected_put(-0x86c, 0x1234, 2)
        expected_put(-0x970, (128 if value else 0) << 8, 2)
        profile = int.from_bytes(code[0xb5c + mode * 4:0xb60 + mode * 4], 'big')
        expected_put(-0x978, profile)
        for name, expected_data in (
            ('code-after.bin', code),
            ('main-after.bin', (CODE / 'CODE_1.bin').read_bytes()),
            ('handles.bin', bytes.fromhex('0036100000362000')),
            ('font.bin', bytes.fromhex('1234')),
            ('card-control.bin', bytes([(0xa5 & 0xfc) | (profile & 3)])),
            ('traps.bin', bytes.fromhex('00360004002ff77a00000020')),
        ):
            assert (folder / f'{phase}-{name}').read_bytes() == expected_data, f'{phase}-{name}'

        world = color.expected_world(world, mode)
        if phase and not direct:
            for offset in (-0x4812, -0x5812):
                for index in range(2048):
                    world[0x5960 + offset + index * 2] |= 1
        for _, _, address in text.visible_cells():
            for offset in (-0x4012, -0x5012):
                world[0x5960 + offset + (address - 0x400) * 2] = 0
        text.MODE, text.GLYPH_BANK = mode, 0 if direct else (128 if value else 0)
        expected = text.expected_frame(driver, text.page_data())
        actual = (folder / f'{phase}-frame.bin').read_bytes()
        actual_world = (folder / f'{phase}-world.bin').read_bytes()
        assert actual_world == world, 'world mismatch: ' + str([(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
        assert actual == expected, f'phase {phase}: pixel/guard mismatch'
        if phase == 1 and direct:
            text.GLYPH_BANK = 128
            assert actual != text.expected_frame(driver, text.page_data()), 'missing redraw control escaped'
        converted = bytes([0x5a]) * 64 + bytes([3 if phase and not direct else 0x5a]) * 16384 + bytes([0x5a]) * 64
        assert (folder / f'{phase}-converted.bin').read_bytes() == converted
        expected_sp = 0x3f0000 if phase == 0 else 0x290200 + (phase - 1) * 8 + (8 if direct else 4)
        assert struct.unpack('>4I', (folder / f'{phase}-state.bin').read_bytes()) == (0x290000 + phase * 32, expected_sp, 0x300000, 0x33445566)
        frames.append(sha(folder / f'{phase}-frame.bin'))
    assert frames[0] == frames[2]
    assert (frames[0] == frames[1]) == direct
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    for offset in (0x35e, 0x3a0, 0x3ae, 0x3b6, 0x404):
        assert pcs.count(0x200000 + offset) == 3
    assert pcs.count(0x20040e) == 1
    assert pcs.count(0x203e94 if driver == 5 else 0x203e5c) == (1920 if direct else 5760)
    return {'driver': driver, 'mode': mode, 'direct_control': direct, 'settings_sequence': [0, 1, 0], 'frame_hashes': frames,
        'run_directory': str(folder), 'host_shutdown': shutdown, 'framebuffer_checks': 3, 'pixels_per_frame': 640 * 480,
        'hashes': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--alternate', action='store_true')
    parser.add_argument('--direct-control', action='store_true')
    args = parser.parse_args()
    result, inputs = execute(args.driver, args.alternate, args.direct_control)
    inputs += [HERE / 'run.py', HERE / 'execute.lua', TEXT / 'run.py', COLOR / 'run.py',
        CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM, MAME]
    record = {'scope': 'Original settings reload and redraw entry 0774, sequence 0/1/0, retained caches/framebuffer; direct-call missing-redraw control; modeled traps/card register and injected mode/settings',
        'runs': [result], 'inputs_sha256': {str(path): sha(path) for path in inputs}}
    name = f'{"control" if args.direct_control else "results"}-{args.driver}-{result["mode"]:02x}.json'
    (HERE / name).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'PASS CODE {args.driver} settings reload 0/1/0 mode {result["mode"]:02x}' + ('; missing redraw detected' if args.direct_control else ''))


if __name__ == '__main__':
    main()
