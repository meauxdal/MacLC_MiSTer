#!/usr/bin/env python3
"""Check original PAGE2 text pixels with modeled glyphs and live native memory."""
import argparse
import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from prepare import HERE, ROOT, WORK, prepare, sha, snapshot_inputs, FIRST_ACK, LAST_ACK

MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def publish(path, text):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text, encoding='ascii')
    temporary.replace(path)


def visible_cells():
    return [(row, col, 0x400 + (row % 8) * 128 + (row // 8) * 40 + col)
            for row in range(24) for col in range(40)]


def glyph_state():
    snapshots, _ = snapshot_inputs()
    font = snapshots['card-display-glyph', 0, 'font.bin'].read_bytes()
    import importlib.util
    path = ROOT / 'fixtures/experiments/card-display-glyph/run.py'
    spec = importlib.util.spec_from_file_location('glyph_oracle', path)
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    bitmap, _ = oracle.expected(font)
    world = snapshots['card-display-glyph', 0, 'world.bin'].read_bytes()
    assert world[0x5960 - 0x2412:0x5960 - 0x1412] == bitmap
    return bitmap


def lookup_tables():
    short, wide = bytearray(), bytearray()
    for value in range(256):
        pixels = [bool(value & (1 << bit)) ^ bool(value & 128) for bit in range(6, -1, -1)]
        packed = sum(15 << (bit * 4) for bit in range(7) if value & (1 << bit))
        short += (packed ^ (0xffffffff if value & 128 else 0)).to_bytes(4, 'big')
        wide += bytes([255 if bit else 0 for bit in pixels] + [255 if value & 128 else 0])
    return short, wide


def expected_frame(driver, source):
    stride = 320 if driver == 5 else 80
    result = bytearray([0x5a]) * (stride * 480 + 128)
    glyphs = glyph_state()
    seen = set()
    for row, col, address in visible_cells():
        value = source[address - 0x400]
        seen.add(value)
        if value < 128:
            char = (value & 31) + (32 if value & 32 else 64)
        else:
            char = value & 127
            if char < 32:
                char += 64
        for line in range(16):
            glyph = int.from_bytes(glyphs[char * 16 + (line // 2) * 2:char * 16 + (line // 2) * 2 + 2], 'big')
            for pixel in range(14):
                ink = (glyph >> (8 - pixel // 2)) & 1
                white = ink if value < 128 else 1 - ink
                color = 15 if white else (3 if 64 <= value < 128 else 0)
                x = (40 if driver == 5 else 32) + col * 14 + pixel
                y = 48 + row * 16 + line
                if driver == 5:
                    index, shift = 64 + y * stride + x // 2, 4 if x % 2 == 0 else 0
                    result[index] = (result[index] & ~(15 << shift)) | (color << shift)
                else:
                    index, shift = 64 + y * stride + x // 8, 7 - x % 8
                    result[index] = (result[index] & ~(1 << shift)) | (white << shift)
    assert seen == set(range(256))
    return result


def page_data():
    return bytes((index * 37 + (index // 256) * 11 + 61) & 255 for index in range(1024))


def check_render(driver, run, snapshots, mode_phase=False):
    original = (CODE / f'CODE_{driver}.bin').read_bytes()
    transformed = bytes(value | 0x80 for value in original[0x1e14:0x1ebc])
    frame = (run / ('mode-frame.bin' if mode_phase else 'frame.bin')).read_bytes()
    expected = expected_frame(driver, page_data())
    assert frame == expected, 'renderer pixel or framebuffer guard mismatch'
    world = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    short, wide = lookup_tables()
    world[0x5960 - 0x2812:0x5960 - 0x2412] = short
    world[0x5960 - 0x3812:0x5960 - 0x3012] = wide
    world[0x5960 - 0x2412:0x5960 - 0x1412] = glyph_state()
    world[0x5960 - 0x1236:0x5960 - 0x1232] = (0xe00000).to_bytes(4, 'big')
    world[0x5960 - 0x88f] = 1 if mode_phase else 4
    world[0x5960 - 0x892] = 0 if mode_phase else 9
    world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
    world[0x5960 - 0x971] = 0x42
    world[0x5960 - 0x974] = 0x42
    world[0x5960 - 0xfde:0x5960 - 0xfdc] = bytes.fromhex('00e0')
    pairs = bytes(value for item in page_data() for value in (1, item))
    world[0x5960 - 0x4012:0x5960 - 0x3812] = pairs
    for _, _, address in visible_cells():
        world[0x5960 - 0x4012 + (address - 0x400) * 2] = 0
    actual_world = (run / ('mode-world.bin' if mode_phase else 'preack-world.bin')).read_bytes()
    assert actual_world == world, 'post-render host world mismatch: ' + str([
        (hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    if not mode_phase:
        code[0x1e14:0x1ebc] = transformed
    assert (run / ('mode-code.bin' if mode_phase else 'code-after.bin')).read_bytes() == code, 'post-render CODE mismatch'
    return world, code


def expected_transactions(seed):
    mask = (seed & 3) | 32
    result = [[False, 8, 33, seed], [True, 8, 33, mask],
        [False, 8, 32, 136], [True, 8, 32, 128], [False, 8, 1, 224], [False, 8, 1, 224],
        [False, 8, 33, mask], [False, 8, 33, mask], [False, 8, 13, 3],
        [True, 8, 33, (seed & 3) | 16], [False, 8, 32, 128], [True, 8, 32, 136],
        [False, 8, 32, 136], [False, 8, 13, 3], [True, 8, 13, 3],
        [False, 8, 8, 0], [True, 16, 28, 2048]]
    result += [[False, 8, 16, value] for value in page_data()]
    result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 49277], [False, 8, 12, 1], [True, 8, 12, 0]]
    assert len(result) == FIRST_ACK
    result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 49277], [False, 8, 12, 4]]
    result += [[False, 8, 33, (seed & 3) | 16]] * 2 + [[True, 8, 12, 0]]
    assert len(result) == LAST_ACK
    return result


def execute(driver, binary, image, bad_glyph=False):
    seed = 252 if driver == 5 else 255
    run = WORK / f'code{driver}-{time.time_ns()}'
    run.mkdir(parents=True)
    lines, outputs = queue.Queue(), []
    rtl = subprocess.Popen(['wsl', '--exec', 'vvp', linux(binary), '+image=' + linux(image),
                            '+trace=' + linux(run / 'captures.txt'),
                            '+instructions=' + linux(run / 'instructions.txt'), '+sys_phase=2', f'+mask={seed}'],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, bufsize=1)
    host = None

    def reader():
        for line in rtl.stdout:
            lines.put(line.strip())
        lines.put(None)

    def receive(marker):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            line = lines.get(timeout=max(0.001, deadline - time.monotonic()))
            assert line is not None, 'RTL exited before ' + marker
            outputs.append(line)
            if line.startswith(marker):
                return line
        raise TimeoutError(marker)

    threading.Thread(target=reader, daemon=True).start()
    transactions = []
    try:
        receive('READY')
        env = dict(os.environ, IIE_DISPATCH_RUN=run.as_posix(),
                   IIE_DISPATCH_CODE=(CODE / f'CODE_{driver}.bin').as_posix(), IIE_DISPATCH_SERVICE='1')
        snapshots, _ = snapshot_inputs()
        env.update(IIE_INIT_WORLD=snapshots['card-display-init', driver, 'world.bin'].as_posix(),
                   IIE_INIT_CODE=snapshots['card-display-init', driver, 'code-after.bin'].as_posix(),
                   IIE_SWITCH_WORLD=snapshots['card-display-switches', driver, 'world.bin'].as_posix(),
                   IIE_FRAME_SIZE=str((320 if driver == 5 else 80) * 480),
                   IIE_WRONG_DESTINATION='0', IIE_BAD_GLYPH=str(int(bad_glyph)),
                   IIE_MAIN_CODE=(CODE / 'CODE_1.bin').as_posix(),
                   IIE_GLYPH_WORLD=snapshots['card-display-glyph', 0, 'world.bin'].as_posix())
        command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
                   '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
                   '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory',
                   str(run / 'nvram'), '-snapshot_directory', str(run / 'snap'),
                   '-noreadconfig', '-nowriteconfig', '-autoboot_script',
                   str(WORK / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
                   '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
        with (run / 'mame.log').open('w') as log:
            host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            expected = expected_transactions(seed)
            for sequence in range(1, LAST_ACK + 1):
                request = run / f'request-{sequence}.txt'
                deadline = time.monotonic() + 20
                while True:
                    try:
                        fields = list(map(int, request.read_text().split()))
                        break
                    except (FileNotFoundError, PermissionError):
                        assert host.poll() is None and time.monotonic() < deadline, 'Missing host request'
                        time.sleep(0.002)
                assert fields[0] == sequence
                assert [bool(fields[1]), fields[2], fields[3]] == expected[sequence - 1][:3], (sequence, fields, expected[sequence - 1])
                if sequence in (FIRST_ACK, LAST_ACK):
                    assert (run / 'main-after.bin').read_bytes() == (CODE / 'CODE_1.bin').read_bytes()
                    try:
                        expected_world, expected_code = check_render(driver, run, snapshots, sequence == FIRST_ACK)
                    except AssertionError as error:
                        if not bad_glyph or sequence != FIRST_ACK or str(error) != 'renderer pixel or framebuffer guard mismatch':
                            raise
                        return {'control': 'corrupted_glyph', 'rejected': str(error),
                                'forwarded_transactions': len(transactions), 'acks_forwarded': 0,
                                'run_directory': str(run), 'rtl_result': outputs[-4:]}
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                response = receive('REPLY').split()
                assert int(response[1]) == sequence
                result = int(response[2])
                assert result == expected[sequence - 1][3], (sequence, result, expected[sequence - 1])
                transactions.append([bool(fields[1]), fields[2], fields[3], result])
                publish(run / f'response-{sequence}.txt', f'OK {result}\n')
            assert host.wait(timeout=20) == 0
        receive('PASS page2 rendered')
        assert rtl.wait(timeout=10) == 0
        assert transactions == expected
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
        assert (run / 'world.bin').read_bytes() == expected_world, 'post-ACK host world mismatch'
        assert (run / 'code-after.bin').read_bytes() == expected_code
        state = (run / 'state.bin').read_bytes()
        assert state == bytes.fromhex('0020281c003f0000'), state.hex()
        pcs = [int(p, 16) - 0x200000 for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        assert pcs[0] == 0x84300
        assert pcs.count(0x8430e) == 128 and pcs.count(0x84314) == 128
        assert pcs.count(0x84360) == 128 and pcs.count(0x8436a) == 128
        assert pcs.count(0x1ebc) == 1 and pcs.count(0x1ecc) == 168
        assert pcs.count(0x81a) == 1 and pcs.count(0x976) == 0 and pcs.count(0x9a4) == 0
        assert pcs.count(0x9cc) == 1024 and pcs.count(0xa7e) == 1
        assert pcs.count(0x1ee0) == 1 and pcs.count(0x1cae) == 2
        clear = 0x4204 if driver == 5 else 0x3fea
        renderer = 0x3fa4 if driver == 5 else 0x3eb4
        drawn = 960
        assert pcs.count(clear) == 960 and pcs.count(renderer) == drawn, (pcs.count(clear), pcs.count(renderer), drawn)
        assert (run / 'instructions.txt').read_text().splitlines()[0].startswith('fa62 d8 ')
        return {'driver': driver, 'run_directory': str(run), 'transactions_checked': len(transactions),
                'state_hex': state.hex(), 'refreshed_page2_bytes': 1024, 'rendered_cells': drawn, 'page2_dirty_holes': 64, 'glyph_source': 'modeled QuickDraw snapshot', 'text_bytes_covered': 256,
                'world_bytes_compared': len(expected_world), 'pixels_checked': 640 * 480,
                'rtl_result': [line for line in outputs if not line.startswith('REPLY')], 'hashes': {p.name: sha(p) for p in
                [run / 'trace.txt', run / 'bus.jsonl', run / 'captures.txt', run / 'instructions.txt',
                 run / 'loaded.bin', run / 'world.bin', run / 'preack-world.bin', run / 'frame.bin',
                 run / 'code-after.bin', run / 'state.bin', run / 'mode-frame.bin',
                 run / 'mode-world.bin', run / 'mode-code.bin', run / 'main-after.bin']}}
    finally:
        if host and host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        if rtl.poll() is None:
            rtl.terminate()
            rtl.wait(timeout=5)
        (run / 'rtl.log').write_text('\n'.join(outputs) + '\n', encoding='ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    dispatch_pins = json.loads((ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json').read_text())['inputs_sha256']
    for path in (CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM):
        assert sha(path) == dispatch_pins[str(path.relative_to(ROOT))], 'changed original input: ' + str(path)
    sources, image, inputs = prepare()
    main_pins = json.loads((ROOT / 'fixtures/experiments/card-display-init/results.json').read_text())['inputs_sha256']
    assert sha(CODE / 'CODE_1.bin') == main_pins[str(CODE / 'CODE_1.bin')]
    binary = WORK / 'bridge.vvp'
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
               '-Ptb_card_platform.FAST=1', '-Ptb_card_platform.BAD_PAUSE=0',
               '-o', linux(binary), *map(linux, sources)]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    runs = [execute(args.driver, binary, image, args.control)]
    lint = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
            '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
            'maclc_iie_binding', *map(linux, sources[1:])]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(lint)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    inputs += [HERE / 'run.py', *sources, CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM]
    output = HERE / ('control-results.json' if args.control else f'results-{args.driver}.json')
    output.write_text(json.dumps({'scope': 'Original PAGE2 40-column text and CODE 1 lookup generation; modeled glyphs and injected mode',
        'runs': runs, 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print(f'PASS driver {args.driver}: ' + ('corrupt glyph rejected before ACK' if args.control else 'PAGE2 text pixels, original lookup tables and two RTIs'))


if __name__ == '__main__':
    main()
