#!/usr/bin/env python3
"""Check original settings-derived glyph bank selection through text pixels."""
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
WORK = ROOT / 'local/experiments/card-glyph-bank-producer'
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


def execute(driver, setting, alternate, control):
    mode = 0xca if alternate else 0x4a
    bank = 128 if setting else 0
    snapshots, inputs = text.snapshot_inputs()
    folder = WORK / f'{driver}-{mode:02x}-{setting:04x}-{int(control)}-{time.time_ns()}'
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
    put(-0x972, mode, 2)
    put(-0x974, mode, 1)
    put(-0x96e, int(alternate), 1)
    put(-0x970, 0x55aa, 2)
    for auxiliary, offset in ((False, -0x4012), (True, -0x5012)):
        pairs = bytes(value for item in text.page_data(auxiliary) for value in (1, item))
        initial[0x5960 + offset:0x5960 + offset + len(pairs)] = pairs
    settings = bytearray((i * 17 + 9) & 255 for i in range(32))
    settings[4:6] = bytes(2)
    settings[6:8] = setting.to_bytes(2, 'big')
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    assert code[0x40e:0x414] == bytes.fromhex('08ed0007f690')
    if control:
        code[0x411] = 6
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
    assert (folder / 'code-after.bin').read_bytes() == code
    assert (folder / 'main-after.bin').read_bytes() == (CODE / 'CODE_1.bin').read_bytes()
    assert (folder / 'settings-after.bin').read_bytes() == settings
    assert (folder / 'handles.bin').read_bytes() == bytes.fromhex('0036100000362000')
    assert (folder / 'font.bin').read_bytes() == bytes.fromhex('1234')
    assert struct.unpack('>4I', (folder / 'state.bin').read_bytes()) == (0x290000, 0x3f0000, 0x300000, 0x33445566)
    world = bytearray(initial)
    world[0x5960 - 0x886:0x5960 - 0x866] = settings
    def expected_put(offset, value, size=4):
        world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    expected_put(-0x862, 0x300000 - 0x11c2)
    expected_put(-0x866, 0x300000 - 0x11c6)
    expected_put(-0x86c, 0x1234, 2)
    expected_put(-0x970, bank << 8, 2)
    profile = int.from_bytes(code[0xb5c + mode * 4:0xb60 + mode * 4], 'big')
    expected_put(-0x978, profile)
    world = color.expected_world(world, mode)
    for _, _, address in text.visible_cells():
        for offset in (-0x4012, -0x5012):
            world[0x5960 + offset + (address - 0x400) * 2] = 0
    text.MODE, text.GLYPH_BANK = mode, bank
    expected = text.expected_frame(driver, text.page_data())
    actual = (folder / 'frame.bin').read_bytes()
    actual_world = (folder / 'world.bin').read_bytes()
    if control:
        assert actual != expected and actual_world != world, 'bank producer control did not change bank/pixels'
    else:
        assert actual_world == world, 'world mismatch: ' + str([(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
        assert actual == expected, 'pixel/guard mismatch'
    assert (folder / 'card-control.bin').read_bytes() == bytes([(0xa5 & 0xfc) | (profile & 3)])
    assert (folder / 'lock.bin').read_bytes() == bytes.fromhex('00360004')
    assert (folder / 'copy.bin').read_bytes() == bytes.fromhex('00362000002ff77a00000020')
    assert (folder / 'unlock.bin').read_bytes() == bytes.fromhex('00360004')
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    for offset in (0x35a, 0x3a0, 0x3ae, 0x3b6, 0x404):
        assert pcs.count(0x200000 + offset) == 1
    assert pcs.count(0x20040e) == int(bool(setting))
    assert pcs.count(0x203e94 if driver == 5 else 0x203e5c) == 1920
    return {'driver': driver, 'mode': mode, 'setting': setting, 'glyph_bank': bank, 'control': control,
        'run_directory': str(folder), 'host_shutdown': shutdown, 'pixels_checked': 640 * 480,
        'hashes': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--setting', type=lambda value: int(value, 0), default=0)
    parser.add_argument('--alternate', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    assert 0 <= args.setting <= 65535
    assert not args.control or args.setting, 'Control requires a nonzero bank setting'
    result, inputs = execute(args.driver, args.setting, args.alternate, args.control)
    inputs += [HERE / 'run.py', HERE / 'execute.lua', TEXT / 'run.py', COLOR / 'run.py',
        CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM, MAME]
    record = {'scope': 'Original settings-derived glyph bank and full PAGE2 text pixels; modeled handle lock/copy/unlock and card control register; injected settings, mode and caches',
        'runs': [result], 'inputs_sha256': {str(path): sha(path) for path in inputs}}
    name = f'results-{args.driver}-{result["mode"]:02x}-{args.setting:04x}.json' if not args.control else f'control-{args.driver}.json'
    (HERE / name).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'PASS CODE {args.driver} bank setting {args.setting:04x} mode {result["mode"]:02x}' + ('; corrupted producer rejected' if args.control else ''))


if __name__ == '__main__':
    main()
