#!/usr/bin/env python3
"""Replay original IRQ traffic through the hardware binding and native SDRAM."""
import json
from pathlib import Path
import shlex
import subprocess
from prepare import HERE, ROOT, BASE, WORK, prepare, sha, once


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    closure = prepare()
    baseline = ROOT / 'fixtures/experiments/maclc-iie-build/binding-results.json'
    manifest = json.loads(baseline.read_text())
    bench_path = BASE / 'tb_binding.sv'
    assert sha(bench_path) == manifest['inputs_sha256'][str(bench_path)], 'stale baseline bench'
    bench = once(bench_path.read_text(), "card_cpu_address != 16'h202F", "card_cpu_address != 16'h203A")
    bench = once(bench, 'capture_count != 39', 'capture_count != 42')
    bench = once(bench, 'stores != 1192', 'stores != 1199')
    bench = once(bench, '    initial begin\n        if (!$value$plusargs("stimulus=%s", stimulus_path))', '''    integer nmis = 0, irqs = 0, rtis = 0, opcodes = 0;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.opcode02_complete) opcodes = opcodes + 1;
        if (dut.platform.card.card.cpu_ready) begin
            if (dut.platform.card.card.vector_pull && card_cpu_address == 16'hFFFA) nmis = nmis + 1;
            if (dut.platform.card.card.vector_pull && card_cpu_address == 16'hFFFE) irqs = irqs + 1;
            if (dut.platform.card.card.rti_done) rtis = rtis + 1;
        end
    end
    initial begin
        if (!$value$plusargs("stimulus=%s", stimulus_path))''')
    bench = once(bench, '        stop_competitors = 1;', '''        if (nmis != 1 || irqs != 1 || rtis != 2 || opcodes != 1 ||
            dut.platform.card.card.nmi_overlay || dut.platform.card.card.irq_level)
            $fatal(1, "IRQ mismatch NMI=%0d IRQ=%0d RTI=%0d opcode=%0d overlay=%b level=%b", nmis, irqs, rtis, opcodes,
                   dut.platform.card.card.nmi_overlay, dut.platform.card.card.irq_level);
        stop_competitors = 1;''')
    bench = once(bench, '        for (i = 0; i < 262144; i = i + 1) begin', '''        // IRQ can arrive before the counter load or its following report store.
        if (memory[16'h01FC / 2][7:0] != 8'h32 && memory[16'h01FC / 2][7:0] != 8'h35)
            $fatal(1, "IRQ return PC outside the observed loop boundaries");
        expected[16'h01FC] = memory[16'h01FC / 2][7:0];
        $display("IRQ NMI=%0d IRQ=%0d RTI=%0d opcode=%0d saved_PC=20%02x", nmis, irqs, rtis, opcodes, expected[16'h01FC]);
        for (i = 0; i < 262144; i = i + 1) begin''')
    testbench = WORK / 'tb_binding.sv'
    testbench.write_text(bench, encoding='ascii')
    binding = ROOT / 'fixtures/experiments/maclc-iie-build/maclc_iie_binding.sv'
    sources = [testbench, binding, *closure, BASE / 'sdram.v']
    binary = WORK / 'binding.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary), *map(linux, sources)])
    measured = ROOT / 'local/experiments/host-execution/rtl-irq-bridge-01'
    events_path = measured / 'bridge.jsonl'
    events = [json.loads(row) for row in events_path.read_text().splitlines()]
    captures = json.loads((measured / 'bridge-result.json').read_text())['captures']
    assert len(events) == 155 and len(captures) == 42
    expected_captures = [(c['status'], int(c['address'], 16), c['data'] if c['write'] else 0) for c in captures]
    runs, inputs = [], [Path(__file__), baseline, bench_path, events_path, measured / 'bridge-result.json', *sources]
    for fork in (0, 1):
        prefix = ROOT / f'local/experiments/card-system-harness/stimulus{fork}.txt'
        old_image = prefix.with_name(f'expected{fork}.hex')
        inputs += [prefix, old_image]
        stimulus = WORK / f'stimulus{fork}.txt'
        stimulus.write_text(prefix.read_text() + ''.join(
            f'{int(w)} {int(bits == 16)} {off} {value} 600\n' for w, bits, off, value in events[139:]), encoding='ascii')
        expected = [int(value, 16) for value in old_image.read_text().split()]
        assert len(expected) == 262144
        expected[0x1FB:0x1FE] = [0x22, 0x35, 0x20]
        expected[0x200A] = 1
        image = WORK / f'expected{fork}.hex'
        image.write_text(''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
        for phase in (2, 7):
            trace = WORK / f'captures-{fork}-{phase}.txt'
            output, errors = wsl(['vvp', linux(binary), '+stimulus=' + linux(stimulus),
                                  '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={phase}'])
            assert not errors and 'PASS PDS=' in output, output + errors
            observed = [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()]
            assert observed == expected_captures, observed[39:]
            print(output, flush=True)
            runs.append({'fork': fork, 'phase_ns': phase, 'result': output, 'capture_sha256': sha(trace)})
    controls = []
    wrapper = WORK / 'card_pds_candidate.sv'
    for pin in ('NMI', 'IRQ'):
        broken = WORK / f'no-{pin.lower()}.sv'
        broken.write_text(once(wrapper.read_text(), '    card_irq_candidate card (',
                               f'    card_irq_candidate #(.SUPPRESS_{pin}(1)) card ('), encoding='ascii')
        variant_sources = [broken if p == wrapper else p for p in sources]
        executable = WORK / f'no-{pin.lower()}.vvp'
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(executable),
             *map(linux, variant_sources)])
        result = subprocess.run(['wsl', '--', 'vvp', linux(executable),
                                 '+stimulus=' + linux(WORK / 'stimulus0.txt'),
                                 '+expected=' + linux(WORK / 'expected0.hex'),
                                 '+trace=' + linux(WORK / f'no-{pin.lower()}-captures.txt')],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'PDS read transaction=' in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'suppressed': pin, 'result': result.stdout.strip()})
        print('PASS suppressed ' + pin + ' fails the original host readback', flush=True)
    _, errors = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                     '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                     'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert '%Warning' not in errors, errors
    (HERE / 'binding-results.json').write_text(json.dumps({
        'scope': 'IRQ hardware binding; full LC aliases; original uploads/host traffic; native SDRAM with chip model',
        'boundary': '203A', 'runs': runs, 'negative_controls': controls, 'memory_bytes_compared': 262144,
        'IRQ_saved_PC': '2032 or 2035; all other expected bytes fixed',
        'lint': 'binding/card closure -Wall passes with filename/unused exclusions',
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
