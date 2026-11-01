#!/usr/bin/env python3
"""Check original service-4 pixels before forwarding its ACK to live RTL."""
import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from prepare import HERE, ROOT, WORK, prepare, sha, snapshot_inputs

MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def publish(path, text):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text, encoding='ascii')
    temporary.replace(path)


COLORS = [15, 3, 6, 5, 9, 14, 13, 7, 10, 2, 12, 4, 8, 1, 11, 0]
MONO = [0x3fff, 0x1ddd, 0x2eee, 0x0ccc, 0x3777, 0x1555, 0x2666, 0x0444,
        0x3bbb, 0x2666, 0x2aaa, 0x0888, 0x0ccc, 0x1111, 0x2222, 0]


def visible_cells():
    return [(row, col, 0x400 + (row % 8) * 128 + (row // 8) * 40 + col)
            for row in range(24) for col in range(40)]


def expected_frame(driver, source):
    stride = 320 if driver == 5 else 80
    result = bytearray([0x5a]) * (stride * 480 + 128)
    cells = 0
    for row, col, address in visible_cells():
        if not 0x650 <= address < 0x6f8:
            continue
        cells += 1
        value = source[address - 0x650]
        for line in range(16):
            color = (value >> (4 if line >= 8 else 0)) & 15
            for pixel in range(14):
                x = (40 if driver == 5 else 32) + col * 14 + pixel
                y = 48 + row * 16 + line
                if driver == 5:
                    index, shift = 64 + y * stride + x // 2, 4 if x % 2 == 0 else 0
                    result[index] = (result[index] & ~(15 << shift)) | (COLORS[color] << shift)
                else:
                    index, shift = 64 + y * stride + x // 8, 7 - x % 8
                    result[index] = (result[index] & ~(1 << shift)) | (((MONO[color] >> (13 - pixel)) & 1) << shift)
    assert cells == 160
    return result


def check_render(driver, run, snapshots):
    original = (CODE / f'CODE_{driver}.bin').read_bytes()
    transformed = bytes(value | 0x80 for value in original[0x1e14:0x1ebc])
    frame = (run / 'frame.bin').read_bytes()
    expected = expected_frame(driver, transformed)
    assert frame == expected, 'renderer pixel or framebuffer guard mismatch'
    world = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    world[0x5960 - 0x1236:0x5960 - 0x1232] = (0xe00000).to_bytes(4, 'big')
    world[0x5960 - 0x88f] = 4
    world[0x5960 - 0x892] = 9
    world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
    pairs = bytes(value for item in transformed for value in (1, item))
    world[0x5960 - 0x4372:0x5960 - 0x4372 + len(pairs)] = pairs
    for _, _, address in visible_cells():
        if 0x650 <= address < 0x6f8:
            world[0x5960 - 0x4812 + (address - 0x400) * 2] = 0
    assert (run / 'preack-world.bin').read_bytes() == world, 'post-render host world mismatch'
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    code[0x1e14:0x1ebc] = transformed
    assert (run / 'code-after.bin').read_bytes() == code, 'post-render CODE mismatch'
    return world, code


def execute(driver, binary, image, wrong_destination=False):
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
                   IIE_WRONG_DESTINATION='1' if wrong_destination else '0')
        command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
                   '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
                   '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory',
                   str(run / 'nvram'), '-snapshot_directory', str(run / 'snap'),
                   '-noreadconfig', '-nowriteconfig', '-autoboot_script',
                   str(WORK / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
                   '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
        with (run / 'mame.log').open('w') as log:
            host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            for sequence in range(1, 17):
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
                if sequence == 16:
                    assert fields == [16, 1, 8, 12, 0], fields
                    if wrong_destination:
                        try:
                            check_render(driver, run, snapshots)
                        except AssertionError as error:
                            assert str(error) == 'renderer pixel or framebuffer guard mismatch', str(error)
                        else:
                            raise AssertionError('wrong destination passed pixel oracle')
                        return {'control': 'destination_plus_one_byte', 'rejected': 'pixel oracle before second ACK',
                                'forwarded_transactions': len(transactions), 'run_directory': str(run),
                                'frame_sha256': sha(run / 'frame.bin')}
                    expected_world, expected_code = check_render(driver, run, snapshots)
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                response = receive('REPLY').split()
                assert int(response[1]) == sequence
                result = int(response[2])
                transactions.append([bool(fields[1]), fields[2], fields[3], result])
                publish(run / f'response-{sequence}.txt', f'OK {result}\n')
            assert host.wait(timeout=20) == 0
        receive('PASS service4 rendered')
        assert rtl.wait(timeout=10) == 0
        expected = [[False, 8, 33, seed], [True, 8, 33, (seed & 3) | 32],
                    [False, 8, 1, 224], [False, 8, 1, 224], [False, 16, 4, 49277],
                    [False, 8, 12, 1], [True, 8, 12, 0]]
        expected += [[False, 8, 1, 224], [False, 8, 1, 224], [False, 16, 4, 49277], [False, 8, 12, 4]]
        expected += [[False, 8, 33, (seed & 3) | 32]] * 4
        expected += [[True, 8, 12, 0]]
        assert transactions == expected
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
        assert (run / 'world.bin').read_bytes() == expected_world, 'post-ACK host world mismatch'
        assert (run / 'code-after.bin').read_bytes() == expected_code
        state = (run / 'state.txt').read_text().strip()
        assert state == 'ack=true service=4 pc=20281c sp=3f0000', state
        pcs = [int(p, 16) - 0x200000 for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        assert pcs[:11] == [0x7ae, 0x7b2, 0x7b6, 0x7bc, 0x7be, 0x7c0, 0x7c2, 0x7c6, 0x7ca, 0x7cc, 0x818], pcs[:11]
        assert pcs.count(0x1ebc) == 1 and pcs.count(0x1ecc) == 168
        assert pcs.count(0xa7e) == 1 and pcs.count(0x1ee0) == 1 and pcs.count(0x1cae) == 2
        clear = 0x438e if driver == 5 else 0x4174
        renderer = 0x4078 if driver == 5 else 0x3f16
        assert pcs.count(clear) == 160 and pcs.count(renderer) == 160
        assert (run / 'instructions.txt').read_text().splitlines()[0].startswith('fa62 d8 ')
        return {'driver': driver, 'run_directory': str(run), 'transactions': transactions,
                'state': state, 'cache_pairs': 168, 'rendered_cells': 160, 'dirty_holes': 8,
                'world_bytes_compared': len(expected_world), 'pixels_checked': 640 * 480,
                'rtl_result': outputs, 'hashes': {p.name: sha(p) for p in
                [run / 'trace.txt', run / 'bus.jsonl', run / 'captures.txt', run / 'instructions.txt',
                 run / 'loaded.bin', run / 'world.bin', run / 'preack-world.bin', run / 'frame.bin',
                 run / 'code-after.bin', run / 'state.txt']}}
    finally:
        if host and host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        if rtl.poll() is None:
            rtl.terminate()
            rtl.wait(timeout=5)
        (run / 'rtl.log').write_text('\n'.join(outputs) + '\n', encoding='ascii')


def main():
    dispatch_pins = json.loads((ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json').read_text())['inputs_sha256']
    for path in (CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM):
        assert sha(path) == dispatch_pins[str(path.relative_to(ROOT))], 'changed original input: ' + str(path)
    assert (CODE / 'CODE_5.bin').read_bytes()[0x4112:0x4152] == b''.join(bytes([color * 17]) * 4 for color in COLORS)
    assert (CODE / 'CODE_6.bin').read_bytes()[0x3f5a:0x3f7a] == b''.join(bits.to_bytes(2, 'big') for bits in MONO)
    sources, image, inputs = prepare()
    binary = WORK / 'bridge.vvp'
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
               '-Ptb_card_platform.FAST=1', '-o', linux(binary), *map(linux, sources)]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    runs = [execute(driver, binary, image) for driver in (5, 6)]
    controls = [execute(5, binary, image, True)]
    lint = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
            '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
            'maclc_iie_binding', *map(linux, sources[1:])]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(lint)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    inputs += [HERE / 'run.py', *sources, CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM]
    (HERE / 'results.json').write_text(json.dumps({'scope': 'Original mode-zero lores rendering with checked initializer snapshots; pixels gate service4 ACK',
        'runs': runs, 'controls': controls, 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS original CODE5/6 service4 pixels before ACK; second RTI; displaced destination rejected')


if __name__ == '__main__':
    main()
