#!/usr/bin/env python3
"""Check original reload caller selection, live PDS control and rendered pixels."""
import argparse
import importlib.util
import json
import os
import re
import shlex
import struct
import subprocess
import sys
import time
from pathlib import Path
from live import Live, linux

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-reload-caller'
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
spec = importlib.util.spec_from_file_location('caller_prepare', HERE / 'prepare.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)
prepare = candidate.prepare


def execute(driver, alternate, control, binary, image):
    mode = 0xca if alternate else 0x4a
    snapshots, inputs = text.snapshot_inputs()
    folder = WORK / f'{driver}-{mode:02x}-{int(control)}-{time.time_ns()}'
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
    put(-0x85a, 0x55aa55aa)
    for auxiliary, offset in ((False, -0x4012), (True, -0x5012)):
        pairs = bytes(value for item in text.page_data(auxiliary) for value in (1, item))
        initial[0x5960 + offset:0x5960 + offset + len(pairs)] = pairs
    settings = bytearray((i * 17 + 9) & 255 for i in range(32))
    settings[4:6] = bytes(2)
    settings[6:8] = bytes(2)
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    assert code[0x40e:0x414] == bytes.fromhex('08ed0007f690')
    if control:
        code[0x22:0x24] = bytes.fromhex('0338')
    files = {'world-input.bin': initial, 'code-input.bin': code, 'settings.bin': settings}
    for name, contents in files.items():
        (folder / name).write_bytes(contents)
    env = dict(os.environ, IIE_BANK_RUN=folder.as_posix(), IIE_BANK_DRIVER=str(driver),
        IIE_MAIN_CODE=(CODE / 'CODE_1.bin').as_posix())
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51', '-skip_gameinfo',
        '-cfg_directory', str(folder / 'cfg'), '-nvram_directory', str(folder / 'nvram'),
        '-snapshot_directory', str(folder / 'snap'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
        '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    session = Live(binary, image, folder)
    process = None
    rejected = None
    try:
        session.receive('READY')
        with (folder / 'mame.log').open('w') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            profile = int.from_bytes(code[0xb5c + mode * 4:0xb60 + mode * 4], 'big')
            def before_ack():
                check_captures(driver, mode, folder, initial, settings, code)
            try:
                session.exchange(process, profile, before_ack)
            except AssertionError as error:
                if not control or str(error) != 'phase 1: pixel/guard mismatch':
                    raise
                rejected = str(error)
                assert len(session.transactions) == 10
                changed = (folder / '1-world.bin').read_bytes()
                assert changed[0x5960 - 0x970:0x5960 - 0x96e] == bytes.fromhex('8000')
                assert (folder / '0-frame.bin').read_bytes() == (folder / '1-frame.bin').read_bytes()
                assert (folder / '1-code-after.bin').read_bytes() == code
            if not rejected:
                assert not control, 'wrong entry escaped pixel checks'
                assert process.wait(timeout=15) == 0
                session.finish()
                _, world = check_captures(driver, mode, folder, initial, settings, code)
                world[0x5960 - 0x88f] = 1
                world[0x5960 - 0x892] = 0
                assert (folder / 'service-world.bin').read_bytes() == world, 'service world mismatch'
                assert (folder / 'service-state.bin').read_bytes() == bytes.fromhex('0020281c003f00000030000033445566')
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        session.close()
    assert '[LUA ERROR]' not in (folder / 'mame.log').read_text()
    return {'driver': driver, 'mode': mode, 'control': control, 'rejected': rejected,
        'settings_sequence': [0, 1, 0], 'run_directory': str(folder),
        'transactions': session.transactions, 'acks_forwarded': int(not rejected),
        'framebuffer_checks': 3 if not rejected else 1,
        'host_shutdown': 'terminated_after_rejection' if rejected else 'exited_zero',
        'rtl_result': [line for line in session.output if not line.startswith('REPLY')],
        'hashes': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}, inputs


def check_captures(driver, mode, folder, initial, settings, code):
    world = bytearray(initial)
    world[0x5960 - 0x85a:0x5960 - 0x856] = (0x200004).to_bytes(4, 'big')
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
            ('card-control.bin', bytes([(0xa1 & 0xfc) | (profile & 3)])),
            ('traps.bin', bytes.fromhex('00360004002ff77a00000020')),
        ):
            assert (folder / f'{phase}-{name}').read_bytes() == expected_data, f'{phase}-{name}'

        world = color.expected_world(world, mode)
        if phase:
            for offset in (-0x4812, -0x5812):
                for index in range(2048):
                    world[0x5960 + offset + index * 2] |= 1
        for _, _, address in text.visible_cells():
            for offset in (-0x4012, -0x5012):
                world[0x5960 + offset + (address - 0x400) * 2] = 0
        text.MODE, text.GLYPH_BANK = mode, 128 if value else 0
        expected = text.expected_frame(driver, text.page_data())
        actual = (folder / f'{phase}-frame.bin').read_bytes()
        actual_world = (folder / f'{phase}-world.bin').read_bytes()
        assert actual == expected, f'phase {phase}: pixel/guard mismatch'
        assert actual_world == world, 'world mismatch: ' + str([(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
        converted = bytes([0x5a]) * 64 + bytes([3 if phase else 0x5a]) * 16384 + bytes([0x5a]) * 64
        assert (folder / f'{phase}-converted.bin').read_bytes() == converted
        expected_sp = 0x3f0000 if phase == 0 else 0x290200 + (phase - 1) * 8 + 4
        assert struct.unpack('>4I', (folder / f'{phase}-state.bin').read_bytes()) == (0x290000 + phase * 32, expected_sp, 0x300000, 0x33445566)
        if phase:
            assert struct.unpack('>8I', (folder / f'{phase}-registers.bin').read_bytes()) == (
                0x11223303, 0x11223304, 0x11223305, 0x11223306, 0x11223307,
                0x22334402, 0x22334403, 0x22334404)
        frames.append(sha(folder / f'{phase}-frame.bin'))
    assert frames[0] == frames[2]
    assert frames[0] != frames[1]
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    for offset in (0x35e, 0x3a0, 0x3ae, 0x3b6, 0x404):
        assert pcs.count(0x200000 + offset) == 3
    assert pcs.count(0x20040e) == 1
    assert pcs.count(0x203e94 if driver == 5 else 0x203e5c) == 5760
    for pc in (0x2849dc, 0x2849f2, 0x2846e6, 0x2846ee, 0x200020, 0x200778):
        assert pcs.count(pc) == 2, (hex(pc), pcs.count(pc))
    assert pcs.count(0x200044) == 1
    return frames, world


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--alternate', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    sources, image, inputs = prepare()
    binary = WORK / 'caller.vvp'
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
        '-Ptb_card_platform.FAST=1', '-o', linux(binary), *map(linux, sources)]
    compiled = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)],
        capture_output=True, text=True, timeout=20)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    result, snapshots = execute(args.driver, args.alternate, args.control, binary, image)
    inputs += snapshots + sources + [HERE / 'live.py', HERE / 'bridge.lua',
        ROOT / 'fixtures/experiments/card-display-glyph/run.py']
    inputs += [HERE / 'run.py', HERE / 'execute.lua', TEXT / 'run.py', COLOR / 'run.py',
        CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM, MAME]
    record = {'scope': 'Original CODE1 selector4 through initialized driver table, settings 0/1/0 and live PDS control; pixels gate original service1 ACK; modeled resource traps and injected settings/display state',
        'runs': [result], 'inputs_sha256': {str(path): sha(path) for path in inputs}}
    name = f'{"control" if args.control else "results"}-{args.driver}-{result["mode"]:02x}.json'
    (HERE / name).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'PASS CODE {args.driver} caller and live reload 0/1/0 mode {result["mode"]:02x}' + ('; wrong reload entry rejected before ACK' if args.control else ''))


if __name__ == '__main__':
    main()
