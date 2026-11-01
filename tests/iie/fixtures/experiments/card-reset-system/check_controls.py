#!/usr/bin/env python3
"""Reject premature reset and CPU admission during pending reset."""
import json
import shlex
import subprocess
from prepare import HERE, ROOT, WORK, once, prepare, sha
from run import linux, wsl


def main():
    closure, _, inputs = prepare()
    manifest_path = HERE / 'results-1.json'
    pins = json.loads(manifest_path.read_text())['inputs_sha256']
    bench = WORK / 'tb_reset.sv'
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    sources = [bench, binding, *closure, controller]
    for path in sources:
        assert sha(path) == pins[str(path)], 'changed reset input: ' + str(path)
    lint_bench = WORK / 'tb_reset_lint.sv'
    lint_text = once(bench.read_text(), '    defparam dut.platform.card.card.PACE_FAST = FAST;\n', '')
    lint_text = once(lint_text,
                     '    defparam dut.platform.card.card.PACE_CLOCK_HZ = STAGE == 4 ? 260000000 : 32500000;\n', '')
    lint_bench.write_text(lint_text, encoding='ascii')
    _, lint = wsl(['verilator', '--lint-only', '--timing', '-Wno-fatal', '-DTB_NO_TRISTATE',
                   '--top-module', 'tb_card_platform', linux(lint_bench), *map(linux, sources[1:])])
    warnings = [line for line in lint.splitlines() if line.startswith('%Warning')]
    assert len(warnings) == 2 and all('sdram.v:' in line and 'WIDTHEXPAND' in line for line in warnings), lint
    candidate = WORK / 'card_irq_candidate.sv'
    original = candidate.read_text()
    early = once(original, 'reset_pending && drained && !cpu_memory_wait;', 'reset_pending;')
    admission = once(original, '&& !unsupported_cpu &&\n                    (!reset_stopping || cpu_memory_wait);',
                     '&& !unsupported_cpu;')
    admission = once(admission, '&& !cpu_memory_wait && !reset_stopping;', '&& !cpu_memory_wait;')
    controls = []
    for name, text, stage, expected in (
        ('early_reset', early, 2, 'reset committed before accepted work drained'),
        ('new_admission', admission, 4, 'reset admitted new CPU work'),
    ):
        broken = WORK / f'{name}.sv'
        broken.write_text(text, encoding='ascii')
        binary = WORK / f'{name}.vvp'
        variant = [broken if path == candidate else path for path in sources]
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
             '-Ptb_card_platform.WRITING=1', f'-Ptb_card_platform.STAGE={stage}',
             '-o', linux(binary), *map(linux, variant)])
        result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join([
            'vvp', linux(binary), '+trace=' + linux(WORK / f'{name}.txt')])],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and expected in result.stdout and not result.stderr, result.stdout + result.stderr
        print('PASS rejected ' + name, flush=True)
        controls.append({'control': name, 'result': result.stdout.strip()})
        inputs.append(broken)
    inputs += [manifest_path, HERE / 'check_controls.py', lint_bench, *sources]
    (HERE / 'control-results.json').write_text(json.dumps({
        'controls': controls, 'lint': 'default-rate full bench: only two existing SDRAM width warnings',
        'inputs_sha256': {str(path): sha(path) for path in inputs}},
        indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
