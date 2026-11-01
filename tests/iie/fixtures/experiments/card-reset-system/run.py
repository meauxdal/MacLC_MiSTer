#!/usr/bin/env python3
"""Bounded reset-stage tests through PDS and native SDRAM command pins."""
import argparse
import importlib.util
import json
from prepare import HERE, ROOT, SAMPLED, BASE_WORK, WORK, once, prepare, sha

spec = importlib.util.spec_from_file_location('sampled_run', SAMPLED / 'run.py')
sampled_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampled_run)
linux, wsl = sampled_run.linux, sampled_run.wsl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fast', type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    closure, _, inputs = prepare()
    original = BASE_WORK / 'tb_binding.sv'
    pins = json.loads((SAMPLED / 'results.json').read_text())['inputs_sha256']
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (original, binding, controller):
        assert sha(path) == pins[str(path)], 'changed input: ' + str(path)
    text = once(original.read_text(), 'parameter FAST = 0',
                'parameter FAST = 0, WRITING = 0, STAGE = 0')
    text = once(text, '    defparam dut.platform.card.card.PACE_FAST = FAST;',
                '    defparam dut.platform.card.card.PACE_FAST = FAST;\n'
                '    defparam dut.platform.card.card.PACE_CLOCK_HZ = STAGE == 4 ? 260000000 : 32500000;')
    text = once(text, 'always #7.69225 clk_mem = !clk_mem;',
                'always #7.69225 if (!pause_mem) clk_mem = !clk_mem;')
    text = once(text, 'ticks > 2000000', 'ticks > 30000')
    marker = '    initial begin\n        if (!$value$plusargs("stimulus=%s", stimulus_path))'
    assert text.count(marker) == 1
    prefix, tail = text.split(marker)
    _, primitive = tail.split('\nmodule altddio_out ', 1)
    sequence = HERE / 'reset_sequence.sv'
    bench = WORK / 'tb_reset.sv'
    bench.write_text(prefix + sequence.read_text() + '\nendmodule\n\nmodule altddio_out ' + primitive,
                     encoding='ascii')
    sources = [bench, binding, *closure, controller]
    runs = []
    for writing, stages in ((0, (0, 1, 4, 5)), (1, (0, 1, 2, 3, 4))):
        for stage in stages:
            binary = WORK / f'reset-{args.fast}-{writing}-{stage}.vvp'
            wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
                 f'-Ptb_card_platform.FAST={args.fast}', f'-Ptb_card_platform.WRITING={writing}',
                 f'-Ptb_card_platform.STAGE={stage}', '-o', linux(binary), *map(linux, sources)])
            for phase in (2, 7):
                trace = WORK / f'reset-{args.fast}-{writing}-{stage}-{phase}.txt'
                output, errors = wsl(['vvp', linux(binary), '+trace=' + linux(trace), f'+sys_phase={phase}'])
                assert 'PASS reset' in output and not errors, output + errors
                expected_trace = ['80 fffc 00', 'e1 c07d 00', '80 fffc 00'] if stage == 5 else ['80 fffc 00', '80 fffc 00']
                assert trace.read_text().splitlines() == expected_trace, trace.read_text()
                print(output, flush=True)
                runs.append({'fast': args.fast, 'write': writing, 'stage': stage, 'phase_ns': phase,
                             'result': output, 'capture_sha256': sha(trace)})
    _, lint = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                   '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                   'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert not lint, lint
    inputs += [HERE / 'run.py', sequence, original, *sources]
    (HERE / f'results-{args.fast}.json').write_text(json.dumps({
        'scope': 'deferred CPU reset; unchanged native SDRAM controller with injected clock pauses',
        'memory_bytes_compared_per_run': 262144, 'runs': runs,
        'lint': 'binding/card -Wall with existing filename/unused/unconnected exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
