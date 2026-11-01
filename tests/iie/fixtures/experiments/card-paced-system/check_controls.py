#!/usr/bin/env python3
"""Qualify the IRQ-loop count difference and reject a bypassed completion gate."""
import json
from pathlib import Path
import re
import shlex
import subprocess
from prepare import HERE, ROOT, WORK, once, prepare, sha
from run import linux, wsl


def main():
    closure, _, _ = prepare()
    manifest_path = HERE / 'results.json'
    manifest = json.loads(manifest_path.read_text())
    original = WORK / 'tb_binding.sv'
    assert sha(original) == manifest['inputs_sha256'][str(original)], 'changed paced bench'
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    bench = once(original.read_text(), '    integer nmis = 0, irqs = 0, rtis = 0, opcodes = 0;', '''    integer counter_loads = 0, counter_branches = 0;
    always @(posedge clk_sys) begin
        if (cpu_ready && dut.platform.card.card.cpu_sync) begin
            if (card_cpu_address == 16'h2032) counter_loads = counter_loads + 1;
            if (card_cpu_address == 16'h2035) counter_branches = counter_branches + 1;
        end
    end
    integer nmis = 0, irqs = 0, rtis = 0, opcodes = 0;''')
    bench = once(bench, '        $fclose(stimulus);', '''        $display("LOOP loads=%0d branches=%0d", counter_loads, counter_branches);
        $fclose(stimulus);''')
    bench_path = WORK / 'tb_controls.sv'
    bench_path.write_text(bench, encoding='ascii')
    sources = [bench_path, binding, *closure, controller]
    stimulus = ROOT / 'local/experiments/card-softswitch/stimulus0.txt'
    expected = ROOT / 'local/experiments/card-softswitch/expected0.hex'
    for path in (binding, controller, stimulus, expected):
        assert sha(path) == manifest['inputs_sha256'][str(path)], 'changed input: ' + str(path)
    runs = []
    counts = []
    for fast in (0, 1):
        binary = WORK / f'loop-{fast}.vvp'
        trace = WORK / f'loop-{fast}.txt'
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
             f'-Ptb_card_platform.FAST={fast}', '-o', linux(binary), *map(linux, sources)])
        output, errors = wsl(['vvp', linux(binary), '+stimulus=' + linux(stimulus),
                              '+expected=' + linux(expected), '+trace=' + linux(trace)])
        assert not errors and 'PASS PDS=' in output, output + errors
        assert sha(trace) == manifest['runs'][0]['capture_sha256'], 'capture trace changed'
        count = tuple(map(int, re.search(r'LOOP loads=(\d+) branches=(\d+)', output).groups()))
        counts.append(count)
        runs.append({'fast': fast, 'result': output, 'counter_loads': count[0], 'branches': count[1]})
        print(output, flush=True)
    # Each additional loop executes LDA abs (4 cycles) and taken BEQ (3 cycles).
    assert tuple(b - a for a, b in zip(*counts)) == (3, 3), counts
    candidate = WORK / 'card_irq_candidate.sv'
    broken = WORK / 'no_completion_gate.sv'
    broken.write_text(once(candidate.read_text(), 'assign cpu_ready = runnable && released && pace_due &&',
                           'assign cpu_ready = runnable && released &&'), encoding='ascii')
    binary = WORK / 'no_completion_gate.vvp'
    variant = [broken if path == candidate else path for path in sources]
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
         '-o', linux(binary), *map(linux, variant)])
    command = ['vvp', linux(binary), '+stimulus=' + linux(stimulus),
               '+expected=' + linux(expected), '+trace=' + linux(WORK / 'no_completion_gate.txt')]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'CPU completion bypassed pacer' in result.stdout and not result.stderr, result.stdout + result.stderr
    print('PASS bypassed completion gate rejected', flush=True)
    inputs = [__file__, HERE / 'prepare.py', HERE / 'run.py', manifest_path, original,
              bench_path, binding, controller, stimulus, expected, *closure]
    (HERE / 'control-results.json').write_text(json.dumps({
        'irq_loop_runs': runs, 'extra_fast_loops': 3, 'extra_fast_cpu_cycles': 21,
        'negative_control': result.stdout.strip(),
        'inputs_sha256': {str(path): sha(path) for path in map(Path, inputs)}},
        indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
