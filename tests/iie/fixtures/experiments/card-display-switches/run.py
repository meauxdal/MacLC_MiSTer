#!/usr/bin/env python3
"""Run all five monitor display switches through original Macintosh code."""
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
            for sequence in range(1, 14 if wrong_status else 29):
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
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                response = receive('REPLY').split()
                assert int(response[1]) == sequence
                result = int(response[2])
                transactions.append([bool(fields[1]), fields[2], fields[3], result])
                publish(run / f'response-{sequence}.txt', f'OK {8 if wrong_status and sequence in (11, 12) else result}\n')
            assert host.wait(timeout=20) == 0
        if wrong_status:
            assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
            assert (run / 'wrong-route.bin').exists() and not (run / 'world.bin').exists()
            trace = (run / 'trace.txt').read_text()
            assert '00200B10:' in trace and '002015B2:' in trace and '00201AC0:' not in trace
            assert transactions == expected_transactions()[:10] + [[False, 8, 1, 224]] * 2 + [
                [False, 16, 4, 49237]]
            return {'control': 'C055_wrong_status_08', 'rejected': 'original slot-device route at 0B10',
                    'trace_sha256': sha(run / 'trace.txt'), 'run_directory': str(run)}
        receive('PASS switch')
        assert rtl.wait(timeout=10) == 0
        assert transactions == expected_transactions()
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
        state = (run / 'state.txt').read_text().strip()
        assert state == 'ack=true service=0 pc=20281c sp=3f0000', state
        assert (run / 'world.bin').read_bytes() == expected_world(0, 0x00080001), 'unexpected host-world mutation'
        poll_states = [(0, 0)] * 4 + [(1, 0x00080001)] * 2 + [(3, 0x00080001)] * 2 + [(1, 0x00080001)] * 2
        for poll, (mode, table) in enumerate(poll_states, 1):
            assert (run / f'poll-{poll}.bin').read_bytes() == expected_world(mode, table), f'poll {poll} host world'
        assert sha(run / 'code-after.bin') == sha(CODE / f'CODE_{driver}.bin')
        pcs = [int(p, 16) - 0x200000 for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        poll_path = [0x281c, 0x2820, 0x2824, 0x2828, 0x282c, 0x2830, 0x2832, 0x2836,
                     0x2838, 0x2c26, 0x135e, 0x1362, 0x1366]
        handlers = [[0x13ba, 0x1630, 0x1634, 0x163a, 0x1654, 0x1656, 0x136e],
            [0x1386, 0x15b2, 0x15b6,
            0x15bc, 0x15be, 0x15c2, 0x15c8, 0x15cc, 0x15d2, 0x15d6,
            0x15dc, 0x15de, 0x136e],
            [0x14d6, 0x1ac0, 0x1ac4, 0x1aca, 0x1acc, 0x1ad0, 0x1ad6,
             0x1ada, 0x1ae0, 0x1ae4, 0x1ae6, 0x1ae8, 0x136e],
            [0x14d2, 0x1a92, 0x1a96, 0x1a9c, 0x1a9e, 0x1aa2, 0x1aa8,
             0x1aac, 0x1ab2, 0x1ab6, 0x1ab8, 0x1aba, 0x136e],
            [0x1382, 0x1584, 0x1588, 0x158e, 0x1590, 0x1594, 0x159a,
             0x159e, 0x15a4, 0x15a8, 0x15ae, 0x15b0, 0x136e]]
        expected_path = [pc for handler in handlers for pc in poll_path + handler]
        assert pcs in (expected_path, expected_path + [0x281c]), pcs
        assert (run / 'instructions.txt').read_text().splitlines()[0].startswith('fa62 d8 ')
        return {'driver': driver, 'run_directory': str(run), 'transactions': transactions, 'state': state,
                'rtl_result': outputs, 'hashes': {p.name: sha(p) for p in
                [run / 'trace.txt', run / 'bus.jsonl', run / 'captures.txt', run / 'instructions.txt',
                 run / 'loaded.bin', run / 'world.bin', run / 'code-after.bin', run / 'state.txt',
                 *[run / f'poll-{poll}.bin' for poll in range(1, 11)]]}}
    finally:
        if host and host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        if rtl.poll() is None:
            rtl.terminate()
            rtl.wait(timeout=5)
        (run / 'rtl.log').write_text('\n'.join(outputs) + '\n', encoding='ascii')


def expected_world(mode, table):
    world = bytearray(0x5c49)
    world[0x5960 - 0x1236:0x5960 - 0x1236 + 4] = (0xe00000).to_bytes(4, 'big')
    world[0x5960 - 0x971] = mode
    world[0x5960 - 0x978:0x5960 - 0x978 + 4] = table.to_bytes(4, 'big')
    return world


def expected_transactions():
    result = []
    for address, control in [(0xc00e, None), (0xc001, 3), (0xc055, 1), (0xc054, 1), (0xc000, 1)]:
        result += [[False, 8, 1, 224]] * 2 + [[False, 16, 4, address], [True, 8, 12, 0]]
        if control is not None:
            result += [[False, 8, 13, control], [True, 8, 13, 1]]
    return result


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
    (HERE / 'results.json').write_text(json.dumps({'scope': 'Five original monitor display-switch handlers; candidate E0 status and injected reset-state host world',
        'runs': runs, 'controls': controls, 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS original CODE5/6 five display switches; wrong-status route rejected; service 1 held')


if __name__ == '__main__':
    main()
