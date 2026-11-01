#!/usr/bin/env python3
"""Exercise original zero-page/protection diagnostics through native SDRAM."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
from prepare import HERE, ROOT, BASE, WORK, prepare, sha, once

sys.path.insert(0, str(ROOT / 'fixtures/experiments/card-interrupt-contract'))
from test_interrupt_model import check_original


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    closure = prepare()
    baseline = ROOT / 'fixtures/experiments/maclc-iie-irq-build/binding-results.json'
    manifest = json.loads(baseline.read_text())
    bench_path = BASE / 'tb_binding.sv'
    assert sha(bench_path) == manifest['inputs_sha256'][str(bench_path)], 'stale IRQ bench'
    bench = once(bench_path.read_text(), "card_cpu_address != 16'h203A", "card_cpu_address != 16'h2040")
    bench = once(bench, 'capture_count != 42', 'capture_count != 46')
    bench = once(bench, 'stores != 1199', 'stores != 1206')
    bench = once(bench, "memory[16'h01FC / 2][7:0] != 8'h32 && memory[16'h01FC / 2][7:0] != 8'h35",
                 "memory[16'h01FC / 2][7:0] != 8'h3F")
    bench = bench.replace('IRQ return PC outside the observed loop boundaries', 'protection JSR stack mismatch')
    bench = bench.replace('IRQ can arrive before the counter load or its following report store.',
                          'The final JSR pushes its return address before the protection test.')
    bench = bench.replace('saved_PC=20%02x', 'final_stack_PC=20%02x')
    bench = once(bench, '    wire controller_ready;', '    wire diagnostic_boundary, diagnostic_fault;\n    wire controller_ready;')
    bench = once(bench, '        stop_competitors = 1;', '''        if (!diagnostic_boundary || diagnostic_fault)
            $fatal(1, "exported diagnostic status mismatch");
        stop_competitors = 1;''')
    testbench = WORK / 'tb_binding.sv'
    testbench.write_text(bench, encoding='ascii')
    binding = WORK / 'maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    sources = [testbench, binding, *closure, controller]
    binary = WORK / 'binding.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary), *map(linux, sources)])
    # Conf $116 and $33A, after the IRQ trace's existing bit-2 set and ACK.
    tail = [(0, 1, 0xE0), (0, 1, 0xE0), (0, 0x0D, 4), (1, 0x0D, 0), (1, 0x0C, 0),
            (0, 1, 0xE0), (0, 1, 0xE0), (0, 0x0C, 0),
            (0, 0x0D, 0), (1, 0x0D, 16), (1, 0x0C, 0),
            (0, 1, 0xE0), (0, 1, 0xE0), (0, 0x0D, 16), (1, 0x0D, 0), (1, 0x0C, 0),
            (0, 1, 0xE0), (0, 1, 0xE0), (1, 0x0C, 0)]
    measured = ROOT / 'local/experiments/host-execution/rtl-irq-bridge-01/bridge-result.json'
    captures = json.loads(measured.read_text())['captures']
    expected_captures = [(c['status'], int(c['address'], 16), c['data'] if c['write'] else 0) for c in captures]
    expected_captures += [(0xE0, 0xC07D, value) for value in (1, 0, 0xFF, 0)]
    runs, inputs = [], [Path(__file__), baseline, bench_path, measured, *sources]
    forks = [ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc',
             ROOT / 'local/experiments/startup-runtime/startup/IIe Startup.rsrc']
    for fork, resource in enumerate(forks):
        check_original(resource)
        prefix, old_image = BASE / f'stimulus{fork}.txt', BASE / f'expected{fork}.hex'
        inputs += [resource, prefix, old_image]
        stimulus = WORK / f'stimulus{fork}.txt'
        stimulus.write_text(prefix.read_text() + ''.join(f'{w} 0 {off} {value} 2000\n' for w, off, value in tail), encoding='ascii')
        expected = [int(value, 16) for value in old_image.read_text().split()]
        assert len(expected) == 262144 and expected[0x26000] == 0 and expected[0x10000] == 0
        expected[0] = 1
        expected[0x1FC] = 0x3F
        expected[0x26000] = 0xFF
        image = WORK / f'expected{fork}.hex'
        image.write_text(''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
        for phase in (2, 7):
            trace = WORK / f'captures-{fork}-{phase}.txt'
            output, errors = wsl(['vvp', linux(binary), '+stimulus=' + linux(stimulus),
                                  '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={phase}'])
            assert not errors and 'PASS PDS=' in output, output + errors
            observed = [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()]
            assert observed == expected_captures, observed[42:]
            print(output, flush=True)
            runs.append({'fork': fork, 'phase_ns': phase, 'result': output, 'capture_sha256': sha(trace)})
    controls = []
    wrapper = BASE / 'card_pds_candidate.sv'
    for parameter, marker in [('IGNORE_AUX_INHIBIT', 'offset=0000000c'), ('IGNORE_FW_PROTECT', 'offset=00000001')]:
        broken = WORK / f'{parameter.lower()}.sv'
        broken.write_text(once(wrapper.read_text(), '    card_irq_candidate card (',
                               f'    card_irq_candidate #(.{parameter}(1)) card ('), encoding='ascii')
        variant_sources = [broken if p == wrapper else p for p in sources]
        executable = WORK / f'{parameter.lower()}.vvp'
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(executable),
             *map(linux, variant_sources)])
        result = subprocess.run(['wsl', '--', 'vvp', linux(executable),
                                 '+stimulus=' + linux(WORK / 'stimulus0.txt'),
                                 '+expected=' + linux(WORK / 'expected0.hex'),
                                 '+trace=' + linux(WORK / f'{parameter.lower()}-captures.txt')],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'PDS read transaction=' in result.stdout and marker in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'parameter': parameter, 'result': result.stdout.strip()})
        print('PASS ' + parameter + ' fails the original host check', flush=True)
    _, errors = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                     '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                     'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert '%Warning' not in errors, errors
    inputs += [ROOT / 'fixtures/experiments/card-interrupt-contract/test_interrupt_model.py']
    (HERE / 'binding-results.json').write_text(json.dumps({
        'scope': 'bounded zero-page inhibit and E000 protection candidates through native SDRAM; no hardware claim',
        'boundary': '2040', 'runs': runs, 'negative_controls': controls, 'memory_bytes_compared': 262144,
        'lint': 'binding/card closure -Wall passes with filename/unused exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
