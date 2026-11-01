#!/usr/bin/env python3
"""Sweep NMI pulse phase and width at the existing sampled CPU boundary."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-interrupt-timing'
CPU = ROOT / 'fixtures/experiments/card-cpu-rtl'
SOURCE = ROOT / 'local/experiments/card-cpu-rtl/source'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def execute(args):
    return subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                          capture_output=True, text=True, timeout=30)


def run(args):
    result = execute(args)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    return result.stdout.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    pins_path = CPU / 'results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    original = [SOURCE / 'cpu_65c02.sv', SOURCE / 'cpu_alu.sv']
    for path in original:
        assert sha(path) == pins['archive:rtl/cpu/wdc65c02/' + path.name]
    banking = CPU / 'card_cpu_bus.sv'
    assert sha(banking) == pins['fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv']
    sources = [ROOT / 'fixtures/experiments/card-cpu-wait/card_wait_cpu_bus.sv',
               ROOT / 'fixtures/experiments/card-cpu-pacing/card_cycle_pacer.sv', banking, *original]
    wait_pins_path = ROOT / 'fixtures/experiments/card-cpu-wait/results.json'
    wait_pins = json.loads(wait_pins_path.read_text())['inputs_sha256']
    for path in sources[:2]:
        assert sha(path) == wait_pins[str(path.relative_to(ROOT)).replace('\\', '/')]
    bench = HERE / 'tb_interrupt_timing.sv'
    binary = WORK / 'timing.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_interrupt_timing', '-o', linux(binary),
         linux(bench), *map(linux, sources)])
    results = []
    for fast in (0, 1):
        output = run(['vvp', linux(binary), f'+fast={fast}'])
        assert output.startswith(f'PASS fast={fast} sweep=320 '), output
        print(output, flush=True)
        results.append(output)
    broken = WORK / 'level_retrigger.sv'
    text = original[0].read_text()
    assert text.count('nmi_pending <= nmi_edge;') == 1
    broken.write_text(text.replace('nmi_pending <= nmi_edge;', 'nmi_pending <= !nmi_n;'), encoding='ascii')
    control_binary = WORK / 'level-retrigger.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_interrupt_timing', '-o', linux(control_binary),
         linux(bench), *map(linux, sources[:-2]), linux(broken), linux(original[1])])
    control = execute(['vvp', linux(control_binary), '+fast=1', '+control=1'])
    assert control.returncode != 0 and 'NMI count phase=0 width=0' in control.stdout and not control.stderr, control.stdout + control.stderr
    print('PASS held-low retrigger control rejected', flush=True)
    inputs = [Path(__file__), bench, pins_path, wait_pins_path, *sources]
    (HERE / 'results.json').write_text(json.dumps({
        'runs': results, 'low_cases_per_rate': 320, 'high_cases_per_rate': 320,
        'phase_offsets_clocks': list(range(64)), 'pulse_widths_clocks': [1, 2, 32, 64, 128],
        'negative_control': control.stdout.strip(),
        'negative_cpu_sha256': sha(broken),
        'inputs_sha256': {str(path.relative_to(ROOT)).replace('\\', '/'): sha(path) for path in inputs}
    }, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
