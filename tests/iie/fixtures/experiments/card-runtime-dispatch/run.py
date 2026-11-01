#!/usr/bin/env python3
"""Execute original driver dispatch on MAME's Macintosh LC 68020."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-runtime-dispatch'
MAME = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
CODE = ROOT / 'local/experiments/firmware-memory/code'
ROM = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'
PINS = {5: '90562edb712c83ca417826eb11bc02f2f3846b2189f64ee8e23158ed5ae31fac',
        6: '72265c3fbab085222fe6cf5fb5dd290708da79efbbb7ae8529232d81727809aa'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(driver, service):
    source = CODE / f'CODE_{driver}.bin'
    assert sha(source) == PINS[driver]
    run = WORK / f'code{driver}-service{service}'
    run.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, IIE_DISPATCH_RUN=run.as_posix(),
               IIE_DISPATCH_CODE=source.as_posix(), IIE_DISPATCH_SERVICE=str(service))
    command = [str(MAME), 'maclc', '-rompath', str(ROM.parent.parent),
               '-ramsize', '4M', '-video', 'none', '-sound', 'none', '-nothrottle',
               '-seconds_to_run', '51', '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'),
               '-nvram_directory', str(run / 'nvram'), '-noreadconfig', '-nowriteconfig',
               '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0',
               '-debug', '-debugger', 'none', '-debugscript',
               str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    with (run / 'mame.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=20)
    assert '[LUA ERROR]' not in (run / 'mame.log').read_text()
    assert sha(run / 'loaded.bin') == PINS[driver], 'Guest code differs from original resource'
    state = (run / 'state.txt').read_text().strip()
    assert f'ack=true service={service}' in state and state.endswith('sp=3f0000'), state
    trace = (run / 'trace.txt').read_text()
    pcs = [int(x, 16) - 0x200000 for x in re.findall(r'^([0-9A-F]{8}):', trace, re.M)]
    end = pcs.index(0x281c, 1)
    expected = [0x281c, 0x2820, 0x2824, 0x2828, 0x282c, 0x2830, 0x2832,
                0x2836, 0x2838, 0x2c26, 0x135e, 0x1362, 0x1366, 0x1576,
                0x1c9a, 0x1c9c, 0x1ca0, 0x1ca4, 0x1ca8, 0x1caa]
    expected += ([0x1cb8, 0x1d28, 0x1d2c, 0x1d30, 0x1d5e] if service == 1
                 else [0x1cb4, 0x1cd4])
    expected += [0x1cae, 0x1cb2, 0x136a]
    assert pcs[:end] == expected
    transactions = [json.loads(x) for x in (run / 'bus.jsonl').read_text().splitlines()]
    expected_bus = [[False, 8, 1, 0xe0], [False, 8, 1, 0xe0],
                    [False, 16, 4, 0xc07d], [False, 8, 12, service], [True, 8, 12, 0]]
    assert transactions[:5] == expected_bus
    assert all(x == [False, 8, 1, 0] for x in transactions[5:])
    return {'driver': driver, 'service': service, 'state': state,
            'dispatch_resource_offsets': [f'{pc:04X}' for pc in pcs[:end + 1]],
            'transactions_through_ack': expected_bus,
            'loaded_code_sha256': sha(run / 'loaded.bin'),
            'trace_sha256': sha(run / 'trace.txt'), 'bus_sha256': sha(run / 'bus.jsonl')}


def main():
    assert sha(ROM) == '129391cc72f84c2b321709cad8281e30a45e50b3cf6e7afe7434c4d32c7b9d5b'
    results = [execute(5, 1), execute(6, 1), execute(5, 0)]
    output = {'scope': 'Injected original driver subset; zero Macintosh sound volume',
              'runs': results, 'inputs_sha256': {str(p.relative_to(ROOT)): sha(p) for p in
              [HERE / 'run.py', HERE / 'execute.lua', CODE / 'CODE_5.bin', CODE / 'CODE_6.bin', ROM]},
              'mame_sha256': sha(MAME)}
    (HERE / 'results.json').write_text(json.dumps(output, indent=2) + '\n', encoding='ascii')
    print('PASS: two original ID1 dispatches and ID0 table-selection control')


if __name__ == '__main__':
    main()
