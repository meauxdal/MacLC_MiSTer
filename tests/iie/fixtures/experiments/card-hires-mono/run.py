#!/usr/bin/env python3
"""Check original monochrome HGR conversion and mixed text without PDS refresh."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-hires-mono'
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'
MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    paths, snapshots = [], {}
    for task in ('card-display-init', 'card-display-glyph'):
        result_path = ROOT / f'fixtures/experiments/{task}/results.json'
        result = json.loads(result_path.read_text())
        for name, digest in result['inputs_sha256'].items():
            assert sha(Path(name)) == digest, name
        run = next(r for r in result['runs'] if r.get('driver') == 6) if task.endswith('init') else next(r for r in result['runs'] if not r['control'])
        for name in (('world.bin', 'code-after.bin') if task.endswith('init') else ('world.bin', 'font.bin')):
            path = Path(run['run_directory']) / name
            assert sha(path) == run['hashes'][name]
            snapshots[task, name] = path
            paths.append(path)
        paths.append(result_path)
    return snapshots, paths


def hgr_address(y, x):
    return (y % 8) * 1024 + ((y // 8) % 8) * 128 + (y // 64) * 40 + x


def raw_image():
    data = bytearray(16384)
    for page in range(2):
        for y in range(192):
            for x in range(40):
                data[page * 8192 + hgr_address(y, x)] = (y * 47 + x * 37 + (x // 3) * 11 + page * 83 + 61) & 255
    return data


def scanline(data, page, y):
    pixels, previous = [], 0
    for x in range(40):
        value = data[page * 8192 + hgr_address(y, x)]
        expanded = [(value >> bit) & 1 for bit in range(7) for _ in range(2)]
        pixels += [previous] + expanded[:13] if value & 128 else expanded
        previous = (value >> 6) & 1
    return pixels


def text_data(aux=False):
    a, b, c = (53, 17, 127) if aux else (37, 11, 61)
    return bytes((i * a + (i // 256) * b + c) & 255 for i in range(1024))


def world_input(snapshots, mode):
    world = bytearray(snapshots['card-display-init', 'world.bin'].read_bytes())
    glyph = snapshots['card-display-glyph', 'world.bin'].read_bytes()[0x5960 - 0x2412:0x5960 - 0x1412]
    world[0x5960 - 0x2412:0x5960 - 0x1412] = glyph
    def put(offset, value, size=4):
        world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    for offset, value in ((-0x1222, 0x320040), (-0x122a, 0x330040),
                          (-0x122e, 0x340040), (-0x1232, 0x343c40)):
        put(offset, value)
    put(-0x974, mode, 1)
    for aux, offset in ((False, -0x4812), (True, -0x5812)):
        pairs = bytes(v for item in text_data(aux) for v in (1, item))
        world[0x5960 + offset:0x5960 + offset + 4096] = pairs * 2
    return world


def expected_world(initial, mode):
    world = bytearray(initial)
    def put(offset, value, size):
        world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    for value in range(256):
        packed = sum(15 << (4 * bit) for bit in range(7) if value & (1 << bit))
        put(-0x2812 + value * 4, packed ^ (0xffffffff if value & 128 else 0), 4)
        wide = bytes([255 if bool(value & (1 << bit)) ^ bool(value & 128) else 0 for bit in range(6, -1, -1)] + [255 if value & 128 else 0])
        world[0x5960 - 0x3812 + value * 8:0x5960 - 0x3812 + value * 8 + 8] = wide
        reverse = int(f'{value & 127:07b}'[::-1], 2)
        put(-0xad8 + value, reverse, 1)
        doubled = sum(3 << (2 * (6 - bit)) for bit in range(7) if value & (1 << bit))
        put(-0xdd8 + value * 2, (~(doubled >> 1) & 65535) if value & 128 else doubled, 2)
        shifted = ((doubled << 1) | (doubled & 1)) & 65535
        put(-0xfd8 + value * 2, (~doubled & 65535) if value & 128 else shifted, 2)
    if mode & 4:
        for row in range(20, 24):
            for col in range(40):
                index = (row % 8) * 128 + (row // 8) * 40 + col
                for offset in ((-0x5812, -0x4812) if mode & 8 else (-0x4812,)):
                    world[0x5960 + offset + (2048 if mode & 2 else 0) + index * 2] = 0
    return world


def expected_cache(data, page):
    cache = bytearray([0x5a]) * (192 * 80 * 2 + 128)
    start = 64 + page * 192 * 80
    for y in range(192):
        row = bytearray(80)
        row[1] = 255
        row[78:80] = bytes.fromhex('edde')
        pixels = scanline(data, page, y)
        for x, bit in enumerate(pixels):
            row[4 + x // 8] |= bit << (7 - x % 8)
        last = page * 8192 + hgr_address(y, 39)
        if data[last + 1] & 128 and data[last] & 64:
            row[74] = 128
        cache[start + y * 80:start + (y + 1) * 80] = row
    return cache


def expected_frame(data, world, mode):
    result = bytearray([0x5a]) * (80 * 480 + 128)
    def pixel(x, y, bit):
        index, shift = 64 + y * 80 + x // 8, 7 - x % 8
        result[index] = (result[index] & ~(1 << shift)) | (bit << shift)
    page, height = int(bool(mode & 2)), 160 if mode & 4 else 192
    for y in range(height):
        for x, bit in enumerate(scanline(data, page, y)):
            for dy in range(2):
                pixel(32 + x, 48 + y * 2 + dy, 1 - bit)
    if mode & 4:
        width = 80 if mode & 8 else 40
        scale = 1 if width == 80 else 2
        for row in range(20, 24):
            for col in range(width):
                index = (row % 8) * 128 + (row // 8) * 40 + col // (2 if width == 80 else 1)
                value = text_data(width == 80 and col % 2 == 0)[index]
                char = (value & 31) + (32 if value & 32 else 64) if value < 128 else (value & 127)
                if value >= 128 and char < 32:
                    char += 64
                for line in range(8):
                    offset = 0x5960 - 0x2412 + char * 16 + line * 2
                    glyph = int.from_bytes(world[offset:offset + 2], 'big')
                    for x in range(7):
                        ink = (glyph >> (8 - x)) & 1
                        for dx in range(scale):
                            for dy in range(2):
                                pixel(32 + col * 7 * scale + x * scale + dx, 48 + row * 16 + line * 2 + dy,
                                      ink if value < 128 else 1 - ink)
    return result


def execute(mode, control):
    snapshots, paths = inputs()
    run = WORK / f'{mode:02x}-{int(control)}-{time.time_ns()}'
    run.mkdir(parents=True)
    initial = world_input(snapshots, mode)
    data = raw_image()
    files = {'world-input.bin': initial, 'code-input.bin': snapshots['card-display-init', 'code-after.bin'].read_bytes(),
             'image-input.bin': b'\x5a' * 64 + data + b'\x5a' * 64,
             'dirty-input.bin': b'\x5a' * 64 + b'\x01' * 16384 + b'\x5a' * 64,
             'cache-input.bin': b'\x5a' * (192 * 80 * 2 + 128), 'frame-input.bin': b'\x5a' * (80 * 480 + 128)}
    for name, contents in files.items():
        (run / name).write_bytes(contents)
    env = dict(os.environ, IIE_HIRES_RUN=run.as_posix(), IIE_HIRES_MODE=str(mode),
               IIE_MAIN_CODE=(CODE / 'CODE_1.bin').as_posix(), IIE_BAD_DESTINATION=str(int(control)))
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51', '-skip_gameinfo',
        '-cfg_directory', str(run / 'cfg'), '-nvram_directory', str(run / 'nvram'),
        '-snapshot_directory', str(run / 'snap'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0',
        '-debug', '-debugger', 'none', '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    (run / 'mame.log').write_text(result.stdout + result.stderr, encoding='ascii')
    assert result.returncode == 0 and '[LUA ERROR]' not in result.stdout + result.stderr
    assert (run / 'image.bin').read_bytes() == files['image-input.bin']
    assert (run / 'code-after.bin').read_bytes() == files['code-input.bin']
    assert (run / 'main-after.bin').read_bytes() == (CODE / 'CODE_1.bin').read_bytes()
    assert struct.unpack('>3I', (run / 'state.bin').read_bytes()) == (0x290000, 0x3f0000, 0x300000)
    world = expected_world(initial, mode)
    frame = expected_frame(data, world, mode)
    actual = (run / 'frame.bin').read_bytes()
    if control:
        assert actual != frame, 'negative control failed to change pixels'
        return {'control': 'destination_plus_one', 'rejected': 'independent pixel/guard oracle', 'run_directory': str(run)}, paths
    assert actual == frame, 'pixel/guard mismatch'
    actual = (run / 'world.bin').read_bytes()
    assert actual == world, [(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual, world)) if a != b][:12]
    cache = expected_cache(data, int(bool(mode & 2)))
    assert (run / 'cache.bin').read_bytes() == cache, 'converted row cache mismatch'
    dirty = bytearray(files['dirty-input.bin'])
    for y in range(192):
        for x in range(40):
            dirty[64 + (8192 if mode & 2 else 0) + hgr_address(y, x)] = 0
    assert (run / 'dirty.bin').read_bytes() == dirty
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
    assert pcs.count(0x204304) == 7680
    assert pcs.count(0x2043e8) == (160 if mode & 4 else 192)
    assert pcs.count(0x2843e8) == 256 and pcs.count(0x28441a) == 256 and pcs.count(0x284458) == 256
    return {'mode': mode, 'run_directory': str(run), 'graphics_rows': 160 if mode & 4 else 192,
            'text_cells': (320 if mode & 8 else 160) if mode & 4 else 0,
            'world_bytes_compared': len(world), 'cache_bytes_compared': len(cache), 'pixels_checked': 640 * 480,
            'hashes': {p.name: sha(p) for p in run.iterdir() if p.is_file()}}, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mixed', choices=('40', '80'))
    parser.add_argument('--page2', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    mode = 0x30 | (2 if args.page2 else 0) | (4 if args.mixed else 0) | (8 if args.mixed == '80' else 0)
    run, paths = execute(mode, args.control)
    paths += [HERE / 'run.py', HERE / 'execute.lua', CODE / 'CODE_1.bin', CODE / 'CODE_6.bin', ROM, MAME]
    output = HERE / ('control-results.json' if args.control else f'results-{mode:02x}.json')
    output.write_text(json.dumps({'scope': 'Original CODE 6 monochrome HGR conversion and mixed rendering; injected memory, no PDS or ACK',
        'runs': [run], 'inputs_sha256': {str(p): sha(p) for p in paths}}, indent=2) + '\n', encoding='ascii')
    print('PASS monochrome hires mode %02x%s' % (mode, ': wrong destination rejected' if args.control else ''))


if __name__ == '__main__':
    main()
