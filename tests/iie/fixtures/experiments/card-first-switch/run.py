#!/usr/bin/env python3
"""Service the held C00E write with original Macintosh driver code."""
import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from prepare import HERE, ROOT, WORK, prepare, sha

MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def publish(path, text):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text, encoding='ascii')
    temporary.replace(path)


def execute(driver, binary, image, wrong_status=False):
    run = WORK / f'code{driver}-{time.time_ns()}'
    run.mkdir(parents=True)
    lines, outputs = queue.Queue(), []
    rtl = subprocess.Popen(['wsl', '--exec', 'vvp', linux(binary), '+image=' + linux(image),
                            '+trace=' + linux(run / 'captures.txt'),
                            '+instructions=' + linux(run / 'instructions.txt'), '+sys_phase=2'],
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
        command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
                   '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
                   '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory',
                   str(run / 'nvram'), '-snapshot_directory', str(run / 'snap'),
                   '-noreadconfig', '-nowriteconfig', '-autoboot_script',
                   str(WORK / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
                   '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
        with (run / 'mame.log').open('w') as log:
            host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            for sequence in range(1, 3 if wrong_status else 5):
                request = run / f'request-{sequence}.txt'
                deadline = time.monotonic() + 20
                while not request.exists():
                    assert host.poll() is None and time.monotonic() < deadline, 'Missing host request'
                    time.sleep(0.002)
                fields = list(map(int, request.read_text().split()))
                assert fields[0] == sequence
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                response = receive('REPLY').split()
                assert int(response[1]) == sequence
                result = int(response[2])
                transactions.append([bool(fields[1]), fields[2], fields[3], result])
                publish(run / f'response-{sequence}.txt', f'OK {8 if wrong_status else result}\n')
            assert host.wait(timeout=20) == 0
        if wrong_status:
            assert (run / 'wrong-route.bin').exists() and not (run / 'world.bin').exists()
            trace = (run / 'trace.txt').read_text()
            assert '00200B10:' in trace and '00201630:' not in trace
            assert transactions == [[False, 8, 1, 224]] * 2
            return {'control': 'wrong_status_08', 'rejected': 'original slot-device route at 0B10',
                    'trace_sha256': sha(run / 'trace.txt'), 'run_directory': str(run)}
        receive('PASS switch')
        assert rtl.wait(timeout=10) == 0
        expected = [[False, 8, 1, 224], [False, 8, 1, 224],
                    [False, 16, 4, 49166], [True, 8, 12, 0]]
        assert transactions == expected
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
        state = (run / 'state.txt').read_text().strip()
        assert state == 'ack=true service=0 pc=20281c sp=3f0000', state
        world = bytearray(0x5c49)
        world[0x5960 - 0x1236:0x5960 - 0x1236 + 4] = (0xe00000).to_bytes(4, 'big')
        assert (run / 'world.bin').read_bytes() == world, 'unexpected host-world mutation'
        assert sha(run / 'code-after.bin') == sha(CODE / f'CODE_{driver}.bin')
        pcs = [int(p, 16) - 0x200000 for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        expected_path = [0x281c, 0x2820, 0x2824, 0x2828, 0x282c, 0x2830, 0x2832, 0x2836,
            0x2838, 0x2c26, 0x135e, 0x1362, 0x1366, 0x13ba, 0x1630, 0x1634, 0x163a,
            0x1654, 0x1656, 0x136e, 0x281c]
        assert pcs == expected_path, pcs
        assert (run / 'instructions.txt').read_text().splitlines()[0].startswith('fa62 d8 ')
        return {'driver': driver, 'run_directory': str(run), 'transactions': transactions, 'state': state,
                'rtl_result': outputs, 'hashes': {p.name: sha(p) for p in
                [run / 'trace.txt', run / 'bus.jsonl', run / 'captures.txt', run / 'instructions.txt',
                 run / 'loaded.bin', run / 'world.bin', run / 'code-after.bin', run / 'state.txt']}}
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
    (HERE / 'results.json').write_text(json.dumps({'scope': 'Original ALTCHAR-off write service; candidate E0 status and injected reset-state host world',
        'runs': runs, 'controls': controls, 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS original CODE5/6 C00E handler; wrong-status route rejected; C001 held')


if __name__ == '__main__':
    main()
