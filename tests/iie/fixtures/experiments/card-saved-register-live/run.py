#!/usr/bin/env python3
"""Run original saved-register handlers against paced card RTL."""
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
from prepare import HERE, ROOT, WORK, prepare, sha

MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def load_render():
    folder = HERE.parent / 'card-service4-render'
    spec = importlib.util.spec_from_file_location('saved_render_prepare', folder / 'prepare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = sys.modules['prepare']
    try:
        sys.modules['prepare'] = module
        spec = importlib.util.spec_from_file_location('saved_render_checks', folder / 'run.py')
        render = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(render)
    finally:
        sys.modules['prepare'] = current
    return render


def check_host(driver, run, snapshots, records, output, render):
    original = (CODE / f'CODE_{driver}.bin').read_bytes()
    transformed = bytes(value | 0x80 for value in original[0x1e14:0x1ebc])
    assert (run / 'frame.bin').read_bytes() == render.expected_frame(driver, transformed)
    world = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    world[0x5960 - 0x1236:0x5960 - 0x1232] = (0xe00000).to_bytes(4, 'big')
    world[0x5960 - 0x88f] = 4
    world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
    pairs = bytes(value for item in transformed for value in (1, item))
    world[0x5960 - 0x4372:0x5960 - 0x4372 + len(pairs)] = pairs
    for _, _, address in render.visible_cells():
        if 0x650 <= address < 0x6f8:
            world[0x5960 - 0x4812 + (address - 0x400) * 2] = 0
    saves = [(int(index), int(value, 16)) for index, value in re.findall(
        r'^SAVE register=(\d) value=([0-9a-f]+)$', '\n'.join(output), re.M)]
    assert len(saves) == 10 and len(records) == 22
    state = list(snapshots['card-display-init', driver, 'world.bin'].read_bytes()[
        0x5960 - 0x894:0x5960 - 0x88f])
    position = 0
    for service in range(2):
        for index, value in saves[service * 5:service * 5 + 5]:
            state[index] = value
            record = records[position]
            assert record[2:4] == [12, 0] and record[4:] == state
            position += 1
        if service == 1:
            state[2] = 9
        assert records[position][2:4] == [12, 0] and records[position][4:] == state
        position += 1
        for index in (4, 3, 2, 1, 0):
            assert records[position][2:4] == [25, state[index]] and records[position][4:] == state
            position += 1
    world[0x5960 - 0x894:0x5960 - 0x88f] = bytes(state)
    assert (run / 'preack-world.bin').read_bytes() == world, 'pre-ACK full host world mismatch'
    assert (run / 'world.bin').read_bytes() == world, 'final full host world mismatch'
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    code[0x1e14:0x1ebc] = transformed
    assert (run / 'code-after.bin').read_bytes() == code, 'full host CODE mismatch'
    assert (run / 'loaded.bin').read_bytes() == original
    assert (run / 'state.txt').read_text().strip() == \
        'services=2 returns=10 transactions=106 pc=20281c sp=3f0000'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    render = load_render()
    snapshots, snapshot_inputs = render.snapshot_inputs()
    sources, image, inputs = prepare()
    binary = WORK / 'bridge.vvp'
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
               '-Ptb_card_platform.FAST=1', '-o', linux(binary), *map(linux, sources)]
    compiled = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    run = WORK / f'code{args.driver}-{time.time_ns()}'
    run.mkdir()
    lines, output, transactions = queue.Queue(), [], []
    rtl = subprocess.Popen(['wsl', '--exec', 'vvp', linux(binary), '+image=' + linux(image),
        '+trace=' + linux(run / 'captures.txt'), '+instructions=' + linux(run / 'instructions.txt'),
        '+sys_phase=2'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1)
    host = None

    def read():
        for line in rtl.stdout:
            lines.put(line.strip())
        lines.put(None)

    def receive(marker):
        deadline = time.monotonic() + 20
        while True:
            line = lines.get(timeout=max(0.001, deadline - time.monotonic()))
            assert line is not None, 'RTL exited before ' + marker
            output.append(line)
            assert not line.startswith('FATAL:'), line
            if line.startswith(marker):
                return line

    threading.Thread(target=read, daemon=True).start()
    rejected = None
    try:
        receive('READY')
        driver = args.driver
        env = dict(os.environ, IIE_DISPATCH_RUN=run.as_posix(),
            IIE_DISPATCH_CODE=(CODE / f'CODE_{driver}.bin').as_posix(),
            IIE_INIT_WORLD=snapshots['card-display-init', driver, 'world.bin'].as_posix(),
            IIE_INIT_CODE=snapshots['card-display-init', driver, 'code-after.bin'].as_posix(),
            IIE_SWITCH_WORLD=snapshots['card-display-switches', driver, 'world.bin'].as_posix(),
            IIE_FRAME_SIZE=str((320 if driver == 5 else 80) * 480),
            IIE_SKIP_SAVED_Y=str(int(args.control)))
        command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
            '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
            '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory', str(run / 'nvram'),
            '-snapshot_directory', str(run / 'snap'), '-noreadconfig', '-nowriteconfig',
            '-autoboot_script', str(HERE / 'host.lua'), '-autoboot_delay', '0',
            '-debug', '-debugger', 'none', '-debugscript',
            str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
        with (run / 'mame.log').open('w') as log:
            host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            sequence = 1
            while True:
                request = run / f'request-{sequence}.txt'
                deadline = time.monotonic() + 20
                while not request.exists():
                    if host.poll() is not None:
                        assert (run / 'world.bin').is_file(), (run / 'mame.log').read_text()
                        break
                    assert time.monotonic() < deadline, 'Missing host request: ' + str(sequence)
                    time.sleep(0.002)
                if not request.exists():
                    break
                fields = list(map(int, request.read_text().split()))
                assert fields[0] == sequence and len(fields) == 5, fields
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                try:
                    reply = receive('REPLY').split()
                except AssertionError as error:
                    if args.control and 'host register return mismatch number=7' in str(error):
                        rejected = str(error)
                        break
                    raise
                assert int(reply[1]) == sequence
                result = int(reply[2])
                transactions.append([bool(fields[1]), fields[2], fields[3], result])
                temporary = run / f'response-{sequence}.tmp'
                temporary.write_text(f'OK {result}\n', encoding='ascii')
                temporary.replace(run / f'response-{sequence}.txt')
                sequence += 1
            if not args.control:
                assert host.wait(timeout=10) == 0
                rtl.stdin.write('-1 0 0 0 0\n')
                rtl.stdin.flush()
                receive('PASS saved-register')
                assert rtl.wait(timeout=10) == 0
            else:
                assert rejected is not None, 'missing saved-Y control escaped'
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        print('\n'.join(output[-12:]), flush=True)
        records = [json.loads(line) for line in (run / 'registers.jsonl').read_text().splitlines()]
        assert len(records) >= 1
        assert [json.loads(line) for line in (run / 'bus.jsonl').read_text().splitlines()] == transactions
        if not args.control:
            pcs = [int(pc, 16) - 0x200000 for pc in re.findall(
                r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
            for offset in (0x1c5e, 0x1c6a, 0x1c76, 0x1c82, 0x1c8e,
                           0x1c2e, 0x1c36, 0x1c3e, 0x1c46, 0x1c4e):
                assert pcs.count(offset) == 2, (hex(offset), pcs.count(offset))
            assert pcs.count(0x1ee0) == 1
            assert sum(write and off == 25 for write, _, off, _ in transactions) == 10
            assert sum(write and off == 12 for write, _, off, _ in transactions) == 12
            assert len(transactions) == 106
            check_host(driver, run, snapshots, records, output, render)
        else:
            assert (run / 'saved-y-fault-pc.bin').read_bytes() == bytes.fromhex('00201ee000201ee6')
            assert (run / 'saved-y-fault-before.bin').read_bytes() == (run / 'saved-y-fault-after.bin').read_bytes()
            assert (run / 'frame.bin').read_bytes() == render.expected_frame(driver,
                bytes(v | 0x80 for v in (CODE / f'CODE_{driver}.bin').read_bytes()[0x1e14:0x1ebc]))
            code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
            code[0x1e14:0x1ebc] = bytes(v | 0x80 for v in (CODE / f'CODE_{driver}.bin').read_bytes()[0x1e14:0x1ebc])
            assert (run / 'loaded.bin').read_bytes() == (CODE / f'CODE_{driver}.bin').read_bytes()
            assert (run / 'code-after.bin').read_bytes() == code
        inputs += snapshot_inputs + [HERE / 'run.py', *sources, MAME, ROM,
            HERE.parent / 'card-service4-render/run.py', CODE / f'CODE_{driver}.bin']
        result = {'scope': 'original CODE saved-register exchange through live PDS and paced CPU; initializer snapshots',
            'driver': driver, 'control': args.control, 'rejected': rejected,
            'run_directory': str(run), 'transactions': transactions, 'register_records': records,
            'rtl_result': output, 'inputs_sha256': {str(p): sha(p) for p in inputs},
            'capture_sha256': {p.name: sha(p) for p in run.iterdir() if p.is_file()}}
        destination = HERE / f'{"control" if args.control else "results"}-{driver}.json'
        destination.write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    finally:
        if host and host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        if rtl.poll() is None:
            rtl.terminate()
            rtl.wait(timeout=5)
        (run / 'rtl.log').write_text('\n'.join(output) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
