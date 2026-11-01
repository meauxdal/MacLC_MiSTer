#!/usr/bin/env python3
"""Bounded interrupt/wait tests using the unchanged archived WDC CPU."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-cpu-wait'
CPU = ROOT / 'fixtures/experiments/card-cpu-rtl'
SOURCE = ROOT / 'local/experiments/card-cpu-rtl/source'
PACE = ROOT / 'fixtures/experiments/card-cpu-pacing'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    pins = json.loads((CPU / 'results.json').read_text())['inputs_sha256']
    original = [SOURCE / 'cpu_65c02.sv', SOURCE / 'cpu_alu.sv']
    for path in original:
        assert sha(path) == pins['archive:rtl/cpu/wdc65c02/' + path.name], 'changed CPU: ' + str(path)
    assert sha(CPU / 'card_cpu_bus.sv') == pins['fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv']
    sources = [HERE / 'card_wait_cpu_bus.sv', PACE / 'card_cycle_pacer.sv',
               CPU / 'card_cpu_bus.sv', *original]
    bench = HERE / 'tb_card_wait_cpu_bus.sv'
    binary = WORK / 'wait.vvp'
    _, errors = wsl(['iverilog', '-g2012', '-s', 'tb_card_wait_cpu_bus', '-o', linux(binary),
                     linux(bench), *map(linux, sources)])
    assert not errors, errors
    cases = ['wai_masked_irq', 'wai_irq', 'wai_nmi', 'read_irq', 'write_irq',
             'read_nmi', 'write_nmi', 'stp_reset', 'reset_held_read', 'reset_held_write',
             'reset_buffered_read', 'reset_buffered_write', 'wai_unsampled_nmi',
             'wai_unmasked_nmi', 'wai_one_sample_nmi']
    results = []
    for fast in (0, 1):
        for number, name in enumerate(cases):
            output, errors = wsl(['vvp', linux(binary), f'+case={number}', f'+fast={fast}'])
            assert output.startswith(f'PASS case={number} fast={fast} ') and not errors, output + errors
            result = output.splitlines()[0]
            print(result, flush=True)
            results.append({'case': name, 'result': result})
    output, errors = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME',
                          '-Wno-PINCONNECTEMPTY', '--top-module', 'card_wait_cpu_bus',
                          *map(linux, sources)])
    assert not errors, output + errors
    broken = WORK / 'no_wai_tick.sv'
    text = sources[0].read_text()
    assert text.count('.rdy(waiting || response_ready)') == 1
    broken.write_text(text.replace('.rdy(waiting || response_ready)', '.rdy(response_ready)'), encoding='ascii')
    negative_binary = WORK / 'no_wai_tick.vvp'
    wsl(['iverilog', '-g2012', '-s', 'tb_card_wait_cpu_bus', '-o', linux(negative_binary),
         linux(bench), linux(broken), *map(linux, sources[1:])])
    negative = subprocess.run(['wsl', '--', 'vvp', linux(negative_binary), '+case=0', '+fast=1'],
                              capture_output=True, text=True, timeout=30)
    assert negative.returncode != 0 and 'timeout case=0' in negative.stdout and not negative.stderr, negative.stdout + negative.stderr
    inputs = [Path(__file__), bench, CPU / 'results.json', *sources]
    manifest = {'runs': results, 'lint': 'PASS -Wall with frozen filename/empty-pin exclusions',
                'negative_control': {'name': 'no_wai_tick', 'failure': negative.stdout.splitlines()[0]},
                'inputs_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in inputs}}
    (HERE / 'results.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
