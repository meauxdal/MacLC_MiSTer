#!/usr/bin/env python3
"""Execute original PixMap stride extraction and absent-EDEF initialization."""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-init'
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'
MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected(driver):
    stride = 320 if driver == 5 else 80
    world = bytearray(0x5c49)

    def put(offset, value, size=4):
        start = 0x5960 + offset
        world[start:start + size] = value.to_bytes(size, 'big')

    for offset, value in [(-0x1208, 0x320000), (-0x85a, 0x200004),
                          (-0x1094, 0x100000), (-0x1066, 0x300000 - 0x2812),
                          (-0x106a, 0x300000 - 0x3812)]:
        put(offset, value)
    for offset, value in [(-0x1096, 640), (-0x10a6, 480),
                          (-0x10a2, 4 if driver == 5 else 1), (-0x1204, 0x1234),
                          (-0x888, stride)]:
        put(offset, value, 2)
    put(-0x85e, 0x100000 + 48 * stride + (20 if driver == 5 else 4))
    for row in range(24):
        put(-0x1062 + row * 4, row * 16 * stride)
    for value in range(128):
        # Seven source bits become seven adjacent two-bit pixels.
        pixels = sum(3 << (2 * bit) for bit in range(7) if value & (1 << bit))
        put(-0xbd8 + value * 2, pixels, 2)
    return world


def table(driver):
    stride = 320 if driver == 5 else 80
    # Apple II HGR address order: five bytes per scan line group, then a hole.
    values = []
    for low in range(8):
        for middle in range(8):
            values += [(low + 8 * (middle + 8 * high)) * (stride // 4) for high in range(3) for _ in range(5)]
            values.append(0)
    return b''.join(value.to_bytes(4, 'big') for value in values)


def execute(driver, corrupt=False):
    run = WORK / f'code{driver}-{time.time_ns()}'
    run.mkdir(parents=True)
    main = CODE / 'CODE_1.bin'
    if corrupt:
        main = run / 'wrong-mask.bin'
        data = bytearray((CODE / 'CODE_1.bin').read_bytes())
        assert data[0x42e2:0x42e6].hex() == '02403fff'
        data[0x42e4:0x42e6] = bytes.fromhex('ffff')
        main.write_bytes(data)
    env = dict(os.environ, IIE_INIT_RUN=run.as_posix(), IIE_INIT_DRIVER=str(driver),
               IIE_INIT_CODE=(CODE / f'CODE_{driver}.bin').as_posix(), IIE_INIT_MAIN=main.as_posix())
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
    assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
    assert sha(run / 'main-loaded.bin') == sha(main)
    assert sha(run / 'main-after.bin') == sha(main)
    assert (run / 'resource-stack.bin').read_bytes() == bytes.fromhex('0a2e45444546000000005678')
    assert (run / 'resource-file.bin').read_bytes() == bytes.fromhex('1234')
    state = (run / 'state.txt').read_text().strip()
    assert state == 'pc=2842f2 sp=3f0000 a6=33445566 d3=11220003 d4=11220004 d5=11220005 d6=11220006 d7=11220007', state
    world = (run / 'world.bin').read_bytes()
    if corrupt:
        assert world != expected(driver)
        assert int.from_bytes(world[0x5960 - 0x888:0x5960 - 0x886], 'big') == 0xc140
        return {'control': 'unmasked_PixMap_rowBytes', 'rejected': 'independent full-world oracle', 'run_directory': str(run)}
    assert world == expected(driver), [(hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(world, expected(driver))) if a != b][:12]
    assert (run / 'low.bin').read_bytes() == bytes.fromhex('5678')
    code = bytearray((CODE / f'CODE_{driver}.bin').read_bytes())
    start = 0x669c if driver == 5 else 0x5378
    generated = table(driver)
    code[start:start + len(generated)] = generated
    assert (run / 'code-after.bin').read_bytes() == code, 'unexpected driver table/code mutation'
    trace = (run / 'trace.txt').read_text()
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', trace, re.M)]
    assert pcs[:8] == [0x2842d4, 0x2842d8, 0x2842dc, 0x2842de, 0x2842e2, 0x2842e6, 0x2842ea, 0x2842ee]
    assert 0x200008 in pcs and 0x20004a in pcs and pcs.count(0x2000d0) == 1 and 0x2000ea in pcs
    assert not any(pc in pcs for pc in (0x2000dc, 0x2000de, 0x2000e2, 0x2000e6))
    assert pcs.count(0x200110) == 960 and pcs.count(0x200124) == 64
    assert pcs.count(0x200150) == 24 and pcs.count(0x200178) == 128
    return {'driver': driver, 'run_directory': str(run), 'state': state,
        'scope': 'original PixMap helper and initializer; modeled A81F NIL result',
        'world_bytes_compared': len(world), 'generated_HGR_table_bytes': len(generated),
        'hashes': {path.name: sha(path) for path in run.iterdir() if path.is_file()}}


def main():
    pins_path = ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    inputs = [CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM]
    for path in inputs:
        assert sha(path) == pins[str(path.relative_to(ROOT))]
    main_code = CODE / 'CODE_1.bin'
    slot_pins = ROOT / 'fixtures/experiments/card-slot3-recovery/results.json'
    assert sha(main_code) == json.loads(slot_pins.read_text())['inputs_sha256'][str(main_code)]
    resource_path = ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc'
    inventory_path = ROOT / 'local/experiments/firmware-memory/resources.json'
    assert sha(resource_path) == json.loads(inventory_path.read_text())['sha256']
    parser_path = ROOT / 'fixtures/research/software-bringup/inspect_resources.py'
    spec = importlib.util.spec_from_file_location('resources', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    assert not any(meta['type'] == 'EDEF' for meta, _ in parser.resources(resource_path.read_bytes()))
    WORK.mkdir(parents=True, exist_ok=True)
    runs = [execute(driver) for driver in (5, 6)]
    controls = [execute(5, True)]
    inputs += [main_code, pins_path, slot_pins, resource_path, inventory_path, parser_path,
               HERE / 'run.py', HERE / 'execute.lua']
    (HERE / 'results.json').write_text(json.dumps({'runs': runs, 'controls': controls,
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS original CODE5/6 PixMap stride and initializer tables; unmasked-rowBytes control rejected')


if __name__ == '__main__':
    main()
