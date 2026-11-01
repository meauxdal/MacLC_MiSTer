#!/usr/bin/env python3
"""Check original glyph ordering and inversion with modeled QuickDraw drawing."""
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
WORK = ROOT / 'local/experiments/card-display-glyph'
CODE = ROOT / 'local/experiments/firmware-memory/code/CODE_2.bin'
FORK = ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc'
INVENTORY = ROOT / 'local/experiments/firmware-memory/resources.json'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'
MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected(font):
    header = struct.unpack_from('>13H', font)
    assert header == (0xb000, 32, 159, 7, 0, 0xffff, 11, 8, 463, 7, 1, 0, 41)
    rows = [int.from_bytes(font[26 + y * 82:26 + (y + 1) * 82], 'big') for y in range(8)]
    locations = struct.unpack_from('>130H', font, 682)
    assert all(a <= b for a, b in zip(locations, locations[1:])) and locations[-1] <= 656
    order = list(range(128, 160)) + list(range(32, 128))
    bitmap = bytearray()
    for char in order:
        index = char - 32
        left, right = locations[index:index + 2]
        bearing, advance = font[942 + 2 * index:944 + 2 * index]
        assert advance == 7 and bearing + right - left <= 7
        for row in rows:
            bits = (row >> (656 - right)) & ((1 << (right - left)) - 1)
            bitmap += (bits << (9 - bearing - (right - left))).to_bytes(2, 'big')
    inverse = b''.join((int.from_bytes(bitmap[i:i + 2], 'big') ^ 0x1fc).to_bytes(2, 'big')
                       for i in range(0, len(bitmap), 2))
    return bitmap + inverse, order


def execute(font, corrupt=False):
    run = WORK / f'{"control" if corrupt else "positive"}-{time.time_ns()}'
    run.mkdir(parents=True)
    (run / 'font.bin').write_bytes(font)
    code = CODE
    if corrupt:
        data = bytearray(CODE.read_bytes())
        assert data[0x498:0x49c].hex() == '323c01fc'
        data[0x49a:0x49c] = bytes.fromhex('03fc')
        code = run / 'wrong-mask.bin'
        code.write_bytes(data)
    env = dict(os.environ, IIE_GLYPH_RUN=run.as_posix(), IIE_GLYPH_CODE=code.as_posix())
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
        '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory', str(run / 'nvram'),
        '-snapshot_directory', str(run / 'snap'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0',
        '-debug', '-debugger', 'none', '-debugscript',
        str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    (run / 'mame.log').write_text(result.stdout + result.stderr, encoding='ascii')
    assert result.returncode == 0 and '[LUA ERROR]' not in result.stdout + result.stderr
    assert (run / 'code-after.bin').read_bytes() == code.read_bytes()
    assert (run / 'font-after.bin').read_bytes() == font
    state = struct.unpack('>9I', (run / 'state.bin').read_bytes())
    assert state == (0x280000, 0x3f0004) + (0x11223344,) * 7, state
    bitmap, order = expected(font)
    world = bytearray(b'\x5a' * 0x5c49)
    def put(offset, value, size):
        world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    put(-0x121a, 2, 2)
    put(-0x121e, 0x300000 - 0x2412, 4)
    for offset, value in enumerate((0, 0, 2048, 16)):
        put(-0x1218 + offset * 2, value, 2)
    world[0x5960 - 0x2412:0x5960 - 0x1412] = bitmap
    actual = (run / 'world.bin').read_bytes()
    if corrupt:
        assert actual != world
        changed = [i for i, (a, b) in enumerate(zip(actual, world)) if a != b]
        assert changed == list(range(0x5960 - 0x1c12, 0x5960 - 0x1412, 2))
    else:
        assert actual == world, [(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual, world)) if a != b][:12]
    calls = (run / 'calls.txt').read_text().splitlines()
    assert calls[:12] == [
        '0368 0800 0010 0000 0000 002f ede8', '036e 003e fff4', '0372 ',
        '038a 0032 0000', '0390 002f ede2', '039a 0400 0010',
        '03a4 002f ede8 0032 1100', '03aa 0032 0010',
        '03b0 0000', '03b6 00c9', '03bc 0008', '03c2 0000']
    chars = [int(line.split()[1], 16) for line in calls if line[:4] in ('03da', '03fc')]
    positions = [tuple(int(v, 16) for v in line.split()[1:]) for line in calls if line[:4] in ('03d2', '03f4')]
    assert chars == order and positions == [(7 + i * 8, 7) for i in range(128)]
    assert [line for line in calls if line.startswith('0418')] == ['0418 6481 464f 4e54']
    trace = (run / 'trace.txt').read_text()
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', trace, re.M)]
    assert pcs.count(0x2004a8) == 1024 and 0x200438 not in pcs
    assert pcs[-2:] == [0x2004d0, 0x280000]
    return {'control': corrupt, 'run_directory': str(run), 'modeled_draw_calls': len(chars),
            'original_inverse_writes': 1024, 'world_bytes_compared': len(world),
            'bitmap_bytes_compared': len(bitmap),
            'expected_bitmap_sha256': hashlib.sha256(bitmap).hexdigest(),
            'hashes': {p.name: sha(p) for p in run.iterdir() if p.is_file()}}


def main():
    inventory = json.loads(INVENTORY.read_text())
    assert sha(FORK) == inventory['sha256']
    parser_path = ROOT / 'fixtures/research/software-bringup/inspect_resources.py'
    spec = importlib.util.spec_from_file_location('resources', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    resources = list(parser.resources(FORK.read_bytes()))
    for meta, payload in resources:
        pin = next(r for r in inventory['resources'] if (r['type'], r['id']) == (meta['type'], meta['id']))
        assert hashlib.sha256(payload).hexdigest() == pin['sha256']
    assert not any(m['type'] == 'FONT' and m['id'] == 0x6481 for m, _ in resources)
    font = next(b for m, b in resources if m['type'] == 'FONT' and m['id'] == 0x6488)
    assert CODE.read_bytes() == next(b for m, b in resources if m['type'] == 'CODE' and m['id'] == 2)
    pins_path = ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json'
    assert sha(ROM) == json.loads(pins_path.read_text())['inputs_sha256'][str(ROM.relative_to(ROOT))]
    runs = [execute(font), execute(font, True)]
    inputs = [CODE, FORK, INVENTORY, ROM, MAME, pins_path, parser_path, HERE / 'run.py', HERE / 'execute.lua']
    (HERE / 'results.json').write_text(json.dumps({'runs': runs,
        'scope': 'Original CODE 2 control and inversion; modeled QuickDraw and Resource Manager',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS original glyph call order and inversion; wrong-mask control rejected')


if __name__ == '__main__':
    main()
