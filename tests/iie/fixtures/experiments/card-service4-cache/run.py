#!/usr/bin/env python3
"""Execute live original service 4 up to its renderer call."""
import hashlib
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


def execute(driver, binary, image):
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
        command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent), '-ramsize', '4M',
                   '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51',
                   '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory',
                   str(run / 'nvram'), '-snapshot_directory', str(run / 'snap'),
                   '-noreadconfig', '-nowriteconfig', '-autoboot_script',
                   str(WORK / 'execute.lua'), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
                   '-debugscript', str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
        with (run / 'mame.log').open('w') as log:
            host = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            for sequence in range(1, 16):
                request = run / f'request-{sequence}.txt'
                deadline = time.monotonic() + 20
                while not request.exists():
                    assert host.poll() is None and time.monotonic() < deadline, 'Missing host request'
                    time.sleep(0.002)
                fields = list(map(int, request.read_text().split()))
                assert fields[0] == sequence
                assert not (sequence > 7 and fields[1] and fields[3] == 12), 'service4 ACK before renderer boundary'
                rtl.stdin.write(' '.join(map(str, fields)) + '\n')
                rtl.stdin.flush()
                response = receive('REPLY').split()
                assert int(response[1]) == sequence
                result = int(response[2])
                transactions.append([bool(fields[1]), fields[2], fields[3], result])
                publish(run / f'response-{sequence}.txt', f'OK {result}\n')
            assert host.wait(timeout=20) == 0
        receive('PASS service4 held')
        assert rtl.wait(timeout=10) == 0
        expected = [[False, 8, 33, seed], [True, 8, 33, (seed & 3) | 32],
                    [False, 8, 1, 224], [False, 8, 1, 224], [False, 16, 4, 49277],
                    [False, 8, 12, 1], [True, 8, 12, 0]]
        expected += [[False, 8, 1, 224], [False, 8, 1, 224], [False, 16, 4, 49277], [False, 8, 12, 4]]
        expected += [[False, 8, 33, (seed & 3) | 32]] * 4
        assert transactions == expected
        assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
        assert sha(run / 'loaded.bin') == sha(CODE / f'CODE_{driver}.bin')
        code = (CODE / f'CODE_{driver}.bin').read_bytes()
        transformed = bytes(value | 0x80 for value in code[0x1e14:0x1ebc])
        after = bytearray(code)
        after[0x1e14:0x1ebc] = transformed
        assert (run / 'code-after.bin').read_bytes() == after, 'unexpected CODE mutation'
        world = bytearray(0x5c49)
        world[0x5960 - 0x1236:0x5960 - 0x1236 + 4] = (0xe00000).to_bytes(4, 'big')
        world[0x5960 - 0x88f] = 4
        pairs = bytes(value for item in transformed for value in (1, item))
        world[0x5960 - 0x4372:0x5960 - 0x4372 + len(pairs)] = pairs
        assert (run / 'world.bin').read_bytes() == world, 'service4 host cache/world mismatch'
        state = (run / 'state.txt').read_text().strip()
        assert state == 'ack=true service=4 pc=200a7e sp=3efff0', state
        pcs = [int(p, 16) - 0x200000 for p in re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        assert pcs[:4] == [0x2c4, 0x2c8, 0x2cc, 0x2d0], pcs[:6]
        pcs = pcs[4:]
        end = pcs.index(0x281c, 1)
        pins = json.loads((ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json').read_text())
        original = next(x for x in pins['runs'] if x['driver'] == driver and x['service'] == 1)
        actual_path = [f'{pc:04X}' for pc in pcs[:end + 1]]
        # MAME traces the breakpoint PC before applying its PC redirection.
        assert actual_path == ['02D4', *original['dispatch_resource_offsets'][1:]], actual_path
        assert pcs.count(0x1ebc) == 1 and pcs.count(0x1ecc) == 2
        assert pcs.count(0x600) == 2 and pcs.count(0x602) == 2
        loops = re.findall(r'loops for (\d+) instructions', (run / 'trace.txt').read_text())
        assert loops == ['664', '498'], loops
        assert 0x76e in pcs and 0x1ee0 not in pcs and 0x1cae not in pcs[end + 1:]
        assert pcs[-1] in (0x76e, 0xa7e), pcs[-6:]
        assert (run / 'instructions.txt').read_text().splitlines()[0].startswith('fa62 d8 ')
        return {'driver': driver, 'run_directory': str(run), 'transactions': transactions,
                'state': state, 'cache_pairs': 168, 'world_bytes_compared': len(world),
                'transformed_source_sha256': hashlib.sha256(transformed).hexdigest(),
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
    inputs += [HERE / 'run.py', *sources, CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM]
    (HERE / 'results.json').write_text(json.dumps({'scope': 'Live original service4 cache update; renderer and second ACK not executed; injected host state',
        'runs': runs, 'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS: original CODE5/6 service4 writes 168 cache pairs; renderer boundary held without ACK')


if __name__ == '__main__':
    main()
