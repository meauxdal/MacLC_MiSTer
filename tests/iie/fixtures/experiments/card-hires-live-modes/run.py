#!/usr/bin/env python3
"""Check live single-hires refresh, rendered pixels and both monitor RTIs."""
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


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def display_mask(mode):
    mask = 64 if mode & 2 else 128
    if mode & 4:
        mask |= 16 if mode & 2 else 32
        if mode & 8:
            mask |= 8
    return mask


def expected_transactions(seed, mode, data):
    page, mask = int(bool(mode & 2)), display_mask(mode)
    result = [[False, 8, 33, seed], [True, 8, 33, (seed & 3) | 32],
        [False, 8, 32, 136], [True, 8, 32, 128], [False, 8, 1, 224], [False, 8, 1, 224],
        [False, 8, 33, (seed & 3) | 32], [False, 8, 33, (seed & 3) | 32], [False, 8, 13, 3],
        [True, 8, 33, (seed & 3) | mask], [False, 8, 32, 128], [True, 8, 32, 136],
        [False, 8, 32, 136], [False, 8, 13, 3], [True, 8, 13, 3]]
    if mode & 4:
        result += [[False, 8, 8, 0], [True, 16, 28, 0x800]]
        if mode & 8:
            result += [[False, 16, 16, (main << 8) | aux] for main, aux in zip(oracle.text_data(), oracle.text_data(True))]
        else:
            result += [[False, 8, 16, value] for value in oracle.text_data()]
    result += [[False, 8, 8, 0], [True, 16, 28, 0x4000 if page else 0x2000]]
    result += [[False, 8, 16, value] for value in data[page * 8192:(page + 1) * 8192]]
    result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 49277], [False, 8, 12, 1], [True, 8, 12, 0]]
    first_ack = len(result)
    result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 49277], [False, 8, 12, 4]]
    mask_reads = 2 if mode & 4 else (4 if page else 3)
    result += [[False, 8, 33, (seed & 3) | mask]] * mask_reads + [[True, 8, 12, 0]]
    return result, first_ack


def check_render(driver, run, snapshots, mode, data, first):
    page = int(bool(mode & 2))
    prefix = 'mode-' if first else ''
    image = bytearray(16384)
    image[page * 8192:(page + 1) * 8192] = data[page * 8192:(page + 1) * 8192]
    assert (run / (prefix + 'image.bin')).read_bytes() == b'\x5a' * 64 + image + b'\x5a' * 64, 'live refresh image/guard mismatch'
    dirty = bytearray(16384)
    dirty[page * 8192:(page + 1) * 8192] = b'\x01' * 8192
    for y in range(192):
        for x in range(40):
            dirty[page * 8192 + oracle.hgr_address(y, x)] = 0
    assert (run / (prefix + 'dirty.bin')).read_bytes() == b'\x5a' * 64 + dirty + b'\x5a' * 64, 'dirty map mismatch'
    assert (run / (prefix + 'cache.bin')).read_bytes() == oracle.expected_cache(image, page), 'converted cache mismatch'
    initial = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    glyphs = snapshots['card-display-glyph', 0, 'world.bin'].read_bytes()
    initial[0x5960 - 0x2412:0x5960 - 0x1412] = glyphs[0x5960 - 0x2412:0x5960 - 0x1412]
    if mode & 4:
        for aux, offset in ((False, -0x4012), (True, -0x5012)):
            if aux and not mode & 8:
                continue
            pairs = bytes(v for item in oracle.text_data(aux) for v in (1, item))
            initial[0x5960 + offset:0x5960 + offset + len(pairs)] = pairs
    world = oracle.expected_world(initial, mode)
    def put(offset, value, size=4):
        world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')
    for offset, value in ((-0x1222, 0x320040), (-0x122a, 0x330040),
                          (-0x122e, 0x340040), (-0x1232, 0x343c40), (-0x1236, 0xe00000)):
        put(offset, value)
    for offset, value in ((-0x88f, 1 if first else 4), (-0x892, 0 if first else 9),
                          (-0x971, mode), (-0x974, mode)):
        put(offset, value, 1)
    put(-0xfde, 224, 2)
    actual_world = (run / ('mode-world.bin' if first else 'preack-world.bin')).read_bytes()
    assert actual_world == world, 'host world mismatch: ' + str([
        (hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
    pixel_oracle = oracle if driver == 5 else mono
    assert (run / ('mode-frame.bin' if first else 'frame.bin')).read_bytes() == pixel_oracle.expected_frame(image, world, mode), 'pixel/guard mismatch'
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
            assert line is not None, 'RTL exited before ' + marker
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
                        if not control or sequence != first_ack or str(error) != 'live refresh image/guard mismatch':
                            raise
                        return {'control': 'shifted_refresh_destination', 'rejected': str(error),
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
        assert pcs.count(0x200a72 if page else 0x200a42) == 8192
        rows = 160 if mode & 4 else 192
        assert pcs.count(0x205520 if driver == 5 else 0x204304) == 7680
        assert pcs.count(0x205608 if driver == 5 else 0x2043e8) == rows
        if mode & 4:
            assert pcs.count(0x200976 if mode & 8 else 0x2009cc) == 1024
            text_loop = (0x203e94 if driver == 5 else 0x203e5c) if mode & 8 else (0x203fa4 if driver == 5 else 0x203eb4)
            assert pcs.count(text_loop) == (320 if mode & 8 else 160)
        assert pcs.count(0x2843e8) == 256 and pcs.count(0x28441a) == 256 and pcs.count(0x284458) == 256
        assert pcs.count(0x20081a) == 1 and pcs.count(0x200a7e) == 1
        assert pcs.count(0x201cae) == 2 and pcs.count(0x201ecc) == 168
        return {'driver': driver, 'mode': mode, 'run_directory': str(run), 'transactions_checked': len(transactions),
            'refresh_bytes': 8192, 'text_refresh_bytes': (2048 if mode & 8 else 1024) if mode & 4 else 0,
            'graphics_rows': rows, 'pixels_checked': 640 * 480,
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
    parser.add_argument('--mixed', choices=('40', '80'))
    parser.add_argument('--page2', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    pins = json.loads((COLOR / 'results-22.json').read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, name
    mono_pins = json.loads((MONO / 'results-32.json').read_text())['inputs_sha256']
    for name, digest in mono_pins.items():
        assert sha(Path(name)) == digest, name
    page = int(args.page2)
    assert not args.mixed or page, 'Mixed PAGE1 service-4 cache updates need separate qualification'
    mode = (0x30 if args.driver == 6 or args.mixed == '80' else 0x20) | page * 2 | (4 if args.mixed else 0) | (8 if args.mixed == '80' else 0)
    sources, image, inputs = prepare()
    data = oracle.raw_image()
    (WORK / 'hires.hex').write_text(''.join(f'{v:02x}\n' for v in data), encoding='ascii')
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
    inputs += [HERE / 'run.py', *sources, WORK / 'hires.hex', COLOR / 'run.py', COLOR / 'artifact.py', COLOR / 'results-22.json', MONO / 'run.py', MONO / 'results-32.json', CODE / 'CODE_1.bin', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM, MAME]
    output = HERE / ('control-results.json' if args.control else f'results-{args.driver}-{mode:02x}.json')
    output.write_text(json.dumps({'scope': 'Original single-hires live PDS refresh and full/mixed rendering before ACK; injected mode, allocation and card RAM fixture',
        'runs': [run], 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS ' + ('shifted refresh rejected before ACK' if args.control else f'CODE {args.driver} mode {mode:02x}: hires refresh, pixels and two RTIs'))
    if run.get('host_shutdown') == 'timeout_after_guest_return':
        print('MAME shutdown timed out after validated guest return; process terminated')


if __name__ == '__main__':
    main()
