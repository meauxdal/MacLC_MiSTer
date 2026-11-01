#!/usr/bin/env python3
"""Check paired double-hires refresh, pixels and both card RTIs."""
import argparse
import importlib.util
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from prepare import HERE, ROOT, WORK, prepare, sha, snapshot_inputs

COLOR = ROOT / 'fixtures/experiments/card-hires-color'
sys.path.insert(0, str(COLOR))
spec = importlib.util.spec_from_file_location('color_oracle', COLOR / 'run.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
MAME, CODE, ROM = oracle.MAME, oracle.CODE, oracle.ROM
MONO = ROOT / 'fixtures/experiments/card-hires-mono'
spec = importlib.util.spec_from_file_location('mono_oracle', MONO / 'run.py')
mono = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mono)
DOUBLE = ROOT / 'fixtures/experiments/card-double-hires'
spec = importlib.util.spec_from_file_location('double_oracle', DOUBLE / 'run.py')
double = importlib.util.module_from_spec(spec)
spec.loader.exec_module(double)


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def display_mask(mode):
    mask = (64 if mode & 2 else 128) | 4
    if mode & 4:
        mask |= 16 if mode & 2 else 32
        if mode & 8:
            mask |= 8
    return mask


def expected_transactions(seed, mode, data):
    main, aux = data
    page, mask = int(bool(mode & 2)), display_mask(mode)
    result = [[False, 8, 33, seed], [True, 8, 33, (seed & 3) | 32],
        [False, 8, 32, 136], [True, 8, 32, 128], [False, 8, 1, 224], [False, 8, 1, 224],
        [False, 8, 33, (seed & 3) | 32], [False, 8, 33, (seed & 3) | 32], [False, 8, 13, 3],
        [True, 8, 33, (seed & 3) | mask], [False, 8, 32, 128], [True, 8, 32, 136],
        [False, 8, 32, 136], [False, 8, 13, 3], [True, 8, 13, 3]]
    if mode & 4:
        result += [[False, 8, 8, 0], [True, 16, 28, 0x800 if page else 0x400]]
        if mode & 8:
            result += [[False, 16, 16, (main << 8) | aux] for main, aux in zip(oracle.text_data(), oracle.text_data(True))]
        else:
            result += [[False, 8, 16, value] for value in oracle.text_data()]
    result += [[False, 8, 8, 0], [True, 16, 28, 0x4000 if page else 0x2000]]
    result += [[False, 16, 16, (m << 8) | a] for m, a in zip(main[page * 8192:(page + 1) * 8192], aux[page * 8192:(page + 1) * 8192])]
    result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 49277], [False, 8, 12, 1], [True, 8, 12, 0]]
    first_ack = len(result)
    result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 49277], [False, 8, 12, 4]]
    mask_reads = 2 if mode & 4 and page else (4 if page else 3)
    result += [[False, 8, 33, (seed & 3) | mask]] * mask_reads + [[True, 8, 12, 0]]
    return result, first_ack


def expected_frame(driver, image, aux, world, mode):
    frame = bytearray(double.expected_frame(driver, image, aux, world, mode))
    if not mode & 4:
        return frame
    stride = 320 if driver == 5 else 80
    width = 80 if mode & 8 else 40
    scale = 1 if width == 80 else 2
    for row in range(20, 24):
        for col in range(width):
            index = (row % 8) * 128 + (row // 8) * 40 + col // (2 if width == 80 else 1)
            offset = -0x5812 if width == 80 and col % 2 == 0 else -0x4812
            value = world[0x5960 + offset + (2048 if mode & 2 else 0) + index * 2 + 1]
            char = (value & 31) + (32 if value & 32 else 64) if value < 128 else value & 127
            if value >= 128 and char < 32:
                char += 64
            for line in range(8):
                offset = 0x5960 - 0x2412 + char * 16 + line * 2
                glyph = int.from_bytes(world[offset:offset + 2], 'big')
                for x in range(7):
                    ink = (glyph >> (8 - x)) & 1
                    white = ink if value < 128 else 1 - ink
                    flashing = 64 <= value < 128
                    if width == 40:
                        color = 15 if white else (3 if flashing else 0)
                    else:
                        shaded = flashing and (col % 2 != 0 or x != 6)
                        color = (3 if shaded else 15) if white else 0
                    for dx in range(scale):
                        for dy in range(2):
                            px = (40 if driver == 5 else 32) + col * 7 * scale + x * scale + dx
                            py = 48 + row * 16 + line * 2 + dy
                            address = 64 + py * stride + px // (2 if driver == 5 else 8)
                            shift = (4 if px % 2 == 0 else 0) if driver == 5 else 7 - px % 8
                            mask = 15 if driver == 5 else 1
                            frame[address] = (frame[address] & ~(mask << shift)) | ((color if driver == 5 else white) << shift)
    return frame


def check_render(driver, run, snapshots, mode, data, first):
    main, auxiliary = data
    page = int(bool(mode & 2))
    prefix = 'mode-' if first else ''
    image = bytearray(16384)
    image[page * 8192:(page + 1) * 8192] = main[page * 8192:(page + 1) * 8192]
    assert (run / (prefix + 'image.bin')).read_bytes() == b'\x5a' * 64 + image + b'\x5a' * 64, 'live refresh image/guard mismatch'
    aux = bytearray(16384)
    aux[page * 8192:(page + 1) * 8192] = auxiliary[page * 8192:(page + 1) * 8192]
    assert (run / (prefix + 'aux.bin')).read_bytes() == b'\x5a' * 64 + aux + b'\x5a' * 64, 'aux refresh image/guard mismatch'
    dirty = bytearray(16384)
    dirty[page * 8192:(page + 1) * 8192] = b'\x03' * 8192
    for y in range(192):
        for x in range(40):
            dirty[page * 8192 + oracle.hgr_address(y, x)] = 0
    assert (run / (prefix + 'dirty.bin')).read_bytes() == b'\x5a' * 64 + dirty + b'\x5a' * 64, 'dirty map mismatch'
    cache = double.expected_cache(image, aux, page)
    assert (run / (prefix + 'cache.bin')).read_bytes() == cache, 'converted cache mismatch'
    initial = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    glyphs = snapshots['card-display-glyph', 0, 'world.bin'].read_bytes()
    initial[0x5960 - 0x2412:0x5960 - 0x1412] = glyphs[0x5960 - 0x2412:0x5960 - 0x1412]
    if mode & 4:
        for is_aux, offset in ((False, -0x4812), (True, -0x5812)):
            if is_aux and not mode & 8:
                continue
            pairs = bytes(v for item in oracle.text_data(is_aux) for v in (1, item))
            start = 0x5960 + offset + page * 2048
            initial[start:start + len(pairs)] = pairs
    if not first and mode & 4 and not page:
        original = (CODE / f'CODE_{driver}.bin').read_bytes()
        pairs = bytes(v for item in original[0x1e14:0x1ebc] for v in (1, item | 128))
        initial[0x5960 - 0x4372:0x5960 - 0x4372 + len(pairs)] = pairs
    world = oracle.expected_world(initial, mode)
    def put(offset, value, size=4):
        world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    for offset, value in ((-0x1222, 0x320040), (-0x1226, 0x350040), (-0x122a, 0x330040),
                          (-0x122e, 0x340040), (-0x1232, 0x343c40), (-0x1236, 0xe00000)):
        put(offset, value)
    for offset, value in ((-0x88f, 1 if first else 4), (-0x892, 0 if first else 9),
                          (-0x971, mode), (-0x974, mode)):
        put(offset, value, 1)
    put(-0xfde, 224, 2)
    actual_world = (run / ('mode-world.bin' if first else 'preack-world.bin')).read_bytes()
    assert actual_world == world, 'host world mismatch: ' + str([
        (hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
    assert (run / ('mode-frame.bin' if first else 'frame.bin')).read_bytes() == expected_frame(driver, image, aux, world, mode), 'pixel/guard mismatch'
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    if not first:
        original = (CODE / f'CODE_{driver}.bin').read_bytes()
        code[0x1e14:0x1ebc] = bytes(value | 128 for value in original[0x1e14:0x1ebc])
    assert (run / ('mode-code.bin' if first else 'code-after.bin')).read_bytes() == code
    assert (run / 'main-after.bin').read_bytes() == (CODE / 'CODE_1.bin').read_bytes()
    return world, code


def execute(binary, firmware, driver, mode, control, data):
    page, seed = int(bool(mode & 2)), 252 if driver == 5 else 255
    expected, first_ack = expected_transactions(seed, mode, data)
    last_ack = len(expected)
    run = WORK / f'{driver}-{mode:02x}-{int(control)}-{time.time_ns()}'
    run.mkdir(parents=True)
    outputs, lines, transactions = [], queue.Queue(), []
    rtl = subprocess.Popen(['wsl', '--exec', 'vvp', linux(binary), '+image=' + linux(firmware),
        '+trace=' + linux(run / 'captures.txt'), '+instructions=' + linux(run / 'instructions.txt'),
        '+sys_phase=2', f'+mask={seed}'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1)
    host = None
    def reader():
        for line in rtl.stdout:
            lines.put(line.strip())
        lines.put(None)
    def receive(marker):
        while True:
            line = lines.get(timeout=20)
            assert line is not None, 'RTL exited before ' + marker + ':\n' + '\n'.join(outputs[-8:])
            outputs.append(line)
            if line.startswith(marker):
                return line
    threading.Thread(target=reader, daemon=True).start()
    started = time.monotonic()
    try:
        receive('READY')
        snapshots, _ = snapshot_inputs()
        env = dict(os.environ, IIE_DISPATCH_RUN=run.as_posix(),
            IIE_DISPATCH_CODE=(CODE / f'CODE_{driver}.bin').as_posix(), IIE_DISPATCH_SERVICE='1',
            IIE_INIT_WORLD=snapshots['card-display-init', driver, 'world.bin'].as_posix(),
            IIE_INIT_CODE=snapshots['card-display-init', driver, 'code-after.bin'].as_posix(),
            IIE_SWITCH_WORLD=snapshots['card-display-switches', driver, 'world.bin'].as_posix(),
            IIE_GLYPH_WORLD=snapshots['card-display-glyph', 0, 'world.bin'].as_posix(),
            IIE_MAIN_CODE=(CODE / 'CODE_1.bin').as_posix(), IIE_FRAME_SIZE=str((320 if driver == 5 else 80) * 480),
            IIE_WRONG_DESTINATION='0', IIE_BAD_GLYPH='0', IIE_GLYPH_BANK='0',
            IIE_BAD_REFRESH=str(int(control)), IIE_TEXT_MODE=str(mode))
        command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
            '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51', '-skip_gameinfo',
            '-cfg_directory', str(run / 'cfg'), '-nvram_directory', str(run / 'nvram'),
            '-snapshot_directory', str(run / 'snap'), '-noreadconfig', '-nowriteconfig',
            '-autoboot_script', str(WORK / 'execute.lua'), '-autoboot_delay', '0',
            '-debug', '-debugger', 'none', '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
        with (run / 'mame.log').open('w') as log:
            host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            for sequence, wanted in enumerate(expected, 1):
                request = run / f'request-{sequence}.txt'
                deadline = time.monotonic() + 20
                while True:
                    try:
                        fields = list(map(int, request.read_text().split()))
                        break
                    except (FileNotFoundError, PermissionError):
                        assert host.poll() is None and time.monotonic() < deadline, 'Missing host request'
                        time.sleep(0.0002)
                assert fields[0] == sequence and [bool(fields[1]), fields[2], fields[3]] == wanted[:3], (sequence, fields, wanted)
                if sequence in (first_ack, last_ack):
                    try:
                        world, code = check_render(driver, run, snapshots, mode, data, sequence == first_ack)
                    except AssertionError as error:
                        if not control or sequence != first_ack or str(error) != 'aux refresh image/guard mismatch':
                            raise
                        return {'control': 'shifted_aux_refresh', 'rejected': str(error),
                            'acks_forwarded': 0, 'transactions_checked': len(transactions), 'run_directory': str(run),
                            'hashes': {p.name: sha(p) for p in run.iterdir() if p.suffix == '.bin'}}
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                response = receive('REPLY').split()
                assert int(response[1]) == sequence and int(response[2]) == wanted[3], (sequence, response, wanted)
                transactions.append(wanted)
                temporary = run / f'response-{sequence}.tmp'
                temporary.write_text(f'OK {response[2]}\n', encoding='ascii')
                temporary.replace(run / f'response-{sequence}.txt')
            receive('PASS page2 rendered')
            assert rtl.wait(timeout=10) == 0
            try:
                assert host.wait(timeout=20) == 0
                shutdown = 'exited_zero'
            except subprocess.TimeoutExpired:
                shutdown = 'timeout_after_guest_return'
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        assert (run / 'world.bin').read_bytes() == world
        assert (run / 'code-after.bin').read_bytes() == code
        assert (run / 'state.bin').read_bytes() == bytes.fromhex('0020281c003f0000')
        assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
        pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        assert pcs.count(0x200a14) == 8192
        rows = 160 if mode & 4 else 192
        passes = 2 if mode & 4 and not page else 1
        assert pcs.count(0x2057a2 if driver == 5 else 0x2044fe) == 7680 * passes
        assert pcs.count(0x20586c if driver == 5 else 0x2045ca) == rows * passes
        if mode & 4:
            assert pcs.count(0x200976 if mode & 8 else 0x2009a4) == 1024
            text_loop = (0x203e94 if driver == 5 else 0x203e5c) if mode & 8 else (0x203fa4 if driver == 5 else 0x203eb4)
            assert pcs.count(text_loop) == 320 + (80 if not page else 0)
        pairs = 168 if mode & 4 and not page else 0
        assert pcs.count(0x200600) == pairs and pcs.count(0x200602) == pairs
        assert pcs.count(0x2843e8) == 256 and pcs.count(0x28441a) == 256 and pcs.count(0x284458) == 256
        assert pcs.count(0x20081a) == 1 and pcs.count(0x200a7e) == passes
        assert pcs.count(0x201cae) == 2 and pcs.count(0x201ecc) == 168
        return {'driver': driver, 'mode': mode, 'run_directory': str(run), 'transactions_checked': len(transactions),
            'refresh_bytes': 16384, 'text_refresh_bytes': 2048 if mode & 4 else 0,
            'graphics_rows': rows, 'pixels_checked': 640 * 480,
            'service4_cache_pairs': pairs, 'service4_text_cells': 80 if pairs else 0,
            'acks_forwarded': 2, 'host_shutdown': shutdown,
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'rtl_result': [line for line in outputs if not line.startswith('REPLY')],
            'hashes': {p.name: sha(p) for p in run.iterdir() if p.suffix == '.bin' or p.name in ('trace.txt', 'bus.jsonl', 'captures.txt', 'instructions.txt')}}
    finally:
        for process in (host, rtl):
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        (run / 'rtl.log').write_text('\n'.join(outputs) + '\n', encoding='ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--mixed', action='store_true')
    parser.add_argument('--page2', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    pins = json.loads((COLOR / 'results-22.json').read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, name
    mono_pins = json.loads((MONO / 'results-32.json').read_text())['inputs_sha256']
    for name, digest in mono_pins.items():
        assert sha(Path(name)) == digest, name
    double_pins = json.loads((DOUBLE / 'results-5-28.json').read_text())['inputs_sha256']
    for path in (DOUBLE / 'run.py', DOUBLE / 'execute.lua'):
        assert sha(path) == double_pins[str(path)], path
    mode = 0x28 | (4 if args.mixed else 0) | (2 if args.page2 else 0)
    sources, image, inputs = prepare()
    data = double.raw_images()
    (WORK / 'hires.hex').write_text(''.join(f'{v:02x}\n' for v in data[0]), encoding='ascii')
    (WORK / 'aux.hex').write_text(''.join(f'{v:02x}\n' for v in data[1]), encoding='ascii')
    binary = WORK / 'bridge.vvp'
    expected, first_ack = expected_transactions(252 if args.driver == 5 else 255, mode, data)
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
        '-Ptb_card_platform.FAST=1', '-Ptb_card_platform.BAD_PAUSE=0',
        f'-Ptb_card_platform.FIRST_ACK={first_ack}', f'-Ptb_card_platform.LAST_ACK={len(expected)}',
        f'-Ptb_card_platform.HIRES_MASK={display_mask(mode)}', '-o', linux(binary), *map(linux, sources)]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    run = execute(binary, image, args.driver, mode, args.control, data)
    lint = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
        '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module', 'maclc_iie_binding', *map(linux, sources[1:])]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(lint)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    inputs += [HERE / 'run.py', *sources, WORK / 'hires.hex', WORK / 'aux.hex', DOUBLE / 'run.py', DOUBLE / 'results-5-28.json', COLOR / 'run.py', COLOR / 'artifact.py', COLOR / 'results-22.json', MONO / 'run.py', MONO / 'results-32.json', CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM, MAME]
    output = HERE / ('control-results.json' if args.control else f'results-{args.driver}-{mode:02x}.json')
    output.write_text(json.dumps({'scope': 'Original paired double-hires PDS refresh and rendering before both ACKs; injected mode, allocation and card RAM fixture',
        'runs': [run], 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS ' + ('shifted auxiliary refresh rejected before first ACK' if args.control else f'CODE {args.driver} mode {mode:02x}: paired double-hires refresh, pixels and two RTIs'))
    if run.get('host_shutdown') == 'timeout_after_guest_return':
        print('MAME shutdown timed out after validated guest return; process terminated')


if __name__ == '__main__':
    main()
