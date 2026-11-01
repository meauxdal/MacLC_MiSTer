#!/usr/bin/env python3
"""Qualify WAI through PDS, CDC mailboxes and the unchanged SDRAM controller."""
import json
import shlex
import subprocess
from prepare import HERE, ROOT, WORK, once, prepare, sha
from run import linux, wsl


def main():
    closure, _, inputs = prepare()
    manifest_path = HERE / 'results.json'
    manifest = json.loads(manifest_path.read_text())
    original = WORK / 'tb_binding.sv'
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (original, binding, controller, *closure):
        assert sha(path) == manifest['inputs_sha256'][str(path)], 'changed sampled input: ' + str(path)
    text = once(original.read_text(), 'parameter FAST = 0', 'parameter FAST = 0, MASKED = 0')
    text = once(text, 'ticks > 2000000', 'ticks > 30000')
    marker = '    initial begin\n        if (!$value$plusargs("stimulus=%s", stimulus_path))'
    assert text.count(marker) == 1
    prefix, tail = text.split(marker)
    _, primitive = tail.split('\nmodule altddio_out ', 1)
    sequence = HERE / 'native_wai_sequence.sv'
    bench = WORK / 'tb_native_wai.sv'
    bench.write_text(prefix + sequence.read_text() + '\nendmodule\n\nmodule altddio_out ' + primitive,
                     encoding='ascii')
    sources = [bench, binding, *closure, controller]
    runs = []
    for fast in (0, 1):
        for masked in (0, 1):
            binary = WORK / f'native-wai-{fast}-{masked}.vvp'
            wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
                 f'-Ptb_card_platform.FAST={fast}', f'-Ptb_card_platform.MASKED={masked}',
                 '-o', linux(binary), *map(linux, sources)])
            for phase in (2, 7):
                trace = WORK / f'native-wai-{fast}-{masked}-{phase}.txt'
                output, errors = wsl(['vvp', linux(binary), '+trace=' + linux(trace), f'+sys_phase={phase}'])
                assert 'PASS native WAI' in output and not errors, output + errors
                assert trace.read_text().splitlines() == ['80 fffc 00', '80 fffc 00'], trace.read_text()
                print(output, flush=True)
                runs.append({'fast': fast, 'masked': masked, 'phase_ns': phase,
                             'result': output, 'capture_sha256': sha(trace)})
    # Verilator 5.032 rejects nested defparam; lint the equivalent default rate.
    lint_bench = WORK / 'tb_native_wai_lint.sv'
    lint_bench.write_text(once(bench.read_text(), '    defparam dut.platform.card.card.PACE_FAST = FAST;\n', ''),
                          encoding='ascii')
    _, lint = wsl(['verilator', '--lint-only', '--timing', '-Wno-fatal', '-DTB_NO_TRISTATE',
                   '--top-module', 'tb_card_platform', linux(lint_bench), *map(linux, sources[1:])])
    warnings = [line for line in lint.splitlines() if line.startswith('%Warning')]
    assert len(warnings) == 2 and all('sdram.v:' in line and 'WIDTHEXPAND' in line for line in warnings), lint
    broken = WORK / 'tb_native_wai_no_irq.sv'
    broken.write_text(once(bench.read_text(), '    defparam dut.platform.card.card.PACE_FAST = FAST;',
                          '    defparam dut.platform.card.card.PACE_FAST = FAST;\n'
                          '    defparam dut.platform.card.card.SUPPRESS_IRQ = 1;'), encoding='ascii')
    binary = WORK / 'native-wai-no-irq.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary),
         linux(broken), *map(linux, sources[1:])])
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join([
        'vvp', linux(binary), '+trace=' + linux(WORK / 'native-wai-no-irq.txt')])],
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'platform watchdog' in result.stdout and not result.stderr, result.stdout + result.stderr
    print('PASS suppressed native WAI IRQ rejected', flush=True)
    inputs += [manifest_path, HERE / 'check_native_wai.py', sequence, original, broken, lint_bench, *sources]
    (HERE / 'native-wai-results.json').write_text(json.dumps({
        'scope': 'synthetic WAI program uploaded through PDS; actual native SDRAM controller and contention',
        'memory_bytes_compared_per_run': 262144, 'runs': runs,
        'lint': 'default-rate full testbench: only two existing SDRAM width warnings',
        'negative_control': result.stdout.strip(),
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
