#!/usr/bin/env python3
"""Check original double-hires conversion and full/mixed rendering."""
import argparse
import hashlib
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
WORK = ROOT / 'local/experiments/card-double-hires'
COLOR = ROOT / 'fixtures/experiments/card-hires-color'
MONO = ROOT / 'fixtures/experiments/card-hires-mono'
sys.path.insert(0, str(COLOR))
spec = importlib.util.spec_from_file_location('single_color', COLOR / 'run.py')
color = importlib.util.module_from_spec(spec)
spec.loader.exec_module(color)
spec = importlib.util.spec_from_file_location('single_mono', MONO / 'run.py')
mono = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mono)
from artifact import decode as waveform_decode

sha, MAME, CODE, ROM = color.sha, color.MAME, color.CODE, color.ROM
PALETTE = (0, 4, 5, 6, 7, 13, 9, 11, 2, 10, 3, 1, 12, 8, 14, 15)


def decode(window):
    return [PALETTE[index] for index in waveform_decode(window)]


def table_image():
    return b''.join(sum(index << (12 - i * 4) for i, index in enumerate(decode(window))).to_bytes(2, 'big')
                    for window in range(2048))


def raw_images():
    main = color.raw_image()
    aux = bytearray(16384)
    for page in range(2):
        for y in range(192):
            for x in range(40):
                aux[page * 8192 + color.hgr_address(y, x)] = (y * 31 + x * 53 + (x // 5) * 19 + page * 97 + 23) & 255
    for page in range(2):
        for y, value in enumerate((0, 127, 255, 128, 0x2a, 0x55, 0xaa, 0xd5)):
            for x in range(40):
                aux[page * 8192 + color.hgr_address(y, x)] = value
    return main, aux


def scanline(main, aux, page, y):
    return [(bank[page * 8192 + color.hgr_address(y, x)] >> bit) & 1
            for x in range(40) for bank in (aux, main) for bit in range(7)]


def expected_cache(main, aux, page):
    cache = bytearray([0x5a]) * (192 * 80 * 2 + 128)
    for y in range(192):
        row = bytearray(80)
        row[1] = 255
        row[78:80] = bytes.fromhex('edde')
        for x, bit in enumerate(scanline(main, aux, page, y)):
            row[4 + x // 8] |= bit << (7 - x % 8)
        start = 64 + page * 192 * 80 + y * 80
        cache[start:start + 80] = row
    return cache


def expected_frame(driver, main, aux, world, mode):
    oracle = color if driver == 5 else mono
    frame = bytearray(oracle.expected_frame(main, world, mode))
    stride = 320 if driver == 5 else 80
    height = 160 if mode & 4 else 192
    page = int(bool(mode & 2))
    for y in range(height):
        samples = scanline(main, aux, page, y)
        for x in range(0, 560, 4):
            window = 0
            for position in range(x - 4, x + 7):
                window = (window << 1) | (samples[position] if 0 <= position < 560 else 0)
            values = decode(window) if driver == 5 else [1 - samples[x + i] for i in range(4)]
            for dx, value in enumerate(values):
                for dy in range(2):
                    px, py = (40 if driver == 5 else 32) + x + dx, 48 + y * 2 + dy
                    address = 64 + py * stride + px // (2 if driver == 5 else 8)
                    shift = (4 if px % 2 == 0 else 0) if driver == 5 else 7 - px % 8
                    mask = 15 if driver == 5 else 1
                    frame[address] = (frame[address] & ~(mask << shift)) | (value << shift)
    return frame


def execute(driver, mode, control):
    oracle = color if driver == 5 else mono
    snapshots, paths = oracle.inputs()
    folder = WORK / f'{driver}-{mode:02x}-{control or "positive"}-{time.time_ns()}'
    folder.mkdir(parents=True)
    initial = oracle.world_input(snapshots, mode)
    initial[0x5960 - 0x1226:0x5960 - 0x1222] = (0x350040).to_bytes(4, 'big')
    main, aux = raw_images()
    files = {'world-input.bin': initial,
        'code-input.bin': snapshots['card-display-init', 'code-after.bin'].read_bytes(),
        'image-input.bin': b'\x5a' * 64 + main + b'\x5a' * 64,
        'aux-input.bin': b'\x5a' * 64 + aux + b'\x5a' * 64,
        'dirty-input.bin': b'\x5a' * 64 + b'\x03' * 16384 + b'\x5a' * 64,
        'cache-input.bin': b'\x5a' * (192 * 80 * 2 + 128),
        'frame-input.bin': b'\x5a' * ((320 if driver == 5 else 80) * 480 + 128)}
    if control == 'table':
        code = bytearray(files['code-input.bin'])
        assert code[0x9440:0x9442] == bytes.fromhex('ffff')
        code[0x9440] ^= 0x10
        files['code-input.bin'] = code
    for name, contents in files.items():
        (folder / name).write_bytes(contents)
    env = dict(os.environ, IIE_HIRES_RUN=folder.as_posix(), IIE_HIRES_MODE=str(mode),
        IIE_MAIN_CODE=(CODE / 'CODE_1.bin').as_posix(), IIE_BAD_DESTINATION='0',
        IIE_DOUBLE_DRIVER=str(driver), IIE_SWAP_BANKS=str(int(control == 'banks')))
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
    assert (folder / 'image.bin').read_bytes() == files['aux-input.bin' if control == 'banks' else 'image-input.bin']
    assert (folder / 'aux.bin').read_bytes() == files['image-input.bin' if control == 'banks' else 'aux-input.bin']
    assert (folder / 'code-after.bin').read_bytes() == files['code-input.bin']
    assert (folder / 'main-after.bin').read_bytes() == (CODE / 'CODE_1.bin').read_bytes()
    assert struct.unpack('>3I', (folder / 'state.bin').read_bytes()) == (0x290000, 0x3f0000, 0x300000)
    world = oracle.expected_world(initial, mode)
    assert (folder / 'world.bin').read_bytes() == world, 'host world mismatch'
    frame = expected_frame(driver, main, aux, world, mode)
    actual = (folder / 'frame.bin').read_bytes()
    if control:
        assert actual != frame, 'control did not change rendered pixels'
    else:
        assert actual == frame, 'pixel/guard mismatch'
        assert (folder / 'cache.bin').read_bytes() == expected_cache(main, aux, int(bool(mode & 2))), 'converted cache mismatch'
        dirty = bytearray(files['dirty-input.bin'])
        for y in range(192):
            for x in range(40):
                dirty[64 + (8192 if mode & 2 else 0) + color.hgr_address(y, x)] = 0
        assert (folder / 'dirty.bin').read_bytes() == dirty, 'dirty map mismatch'
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    assert pcs.count(0x2057a2 if driver == 5 else 0x2044fe) == 7680
    assert pcs.count(0x20586c if driver == 5 else 0x2045ca) == (160 if mode & 4 else 192)
    assert pcs.count(0x2843e8) == 256 and pcs.count(0x28441a) == 256 and pcs.count(0x284458) == 256
    return {'driver': driver, 'mode': mode, 'control': control, 'rejected': 'independent pixel/guard oracle' if control else None,
        'run_directory': str(folder), 'host_shutdown': shutdown, 'pixels_checked': 640 * 480,
        'graphics_rows': 160 if mode & 4 else 192, 'converted_pairs': 7680,
        'hashes': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--page2', action='store_true')
    parser.add_argument('--mixed', action='store_true')
    parser.add_argument('--control', choices=('table', 'banks'))
    args = parser.parse_args()
    assert args.control != 'table' or args.driver == 5, 'Table control requires CODE 5'
    table = (CODE / 'CODE_5.bin').read_bytes()[0x9440:0xa440]
    assert table_image() == table, 'reconstructed double-hires mapping differs from original'
    mode = 0x28 | (2 if args.page2 else 0) | (4 if args.mixed else 0)
    result, paths = execute(args.driver, mode, args.control)
    paths += [HERE / 'run.py', HERE / 'execute.lua', COLOR / 'run.py', COLOR / 'artifact.py', MONO / 'run.py',
        CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM, MAME]
    name = f'control-{args.driver}-{args.control}.json' if args.control else f'results-{args.driver}-{mode:02x}.json'
    record = {'scope': 'Original double-hires renderers with injected main/aux memory and mode; no live PDS refresh or ACK',
        'runs': [result], 'double_table_words_checked': 2048,
        'double_table_sha256': hashlib.sha256(table).hexdigest(), 'inputs_sha256': {str(p): sha(p) for p in paths}}
    (HERE / name).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'PASS double-hires CODE {args.driver} mode {mode:02x}' + (f': {args.control} control rejected' if args.control else ''))


if __name__ == '__main__':
    main()
