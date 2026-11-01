#!/usr/bin/env python3
"""Run the unmodified diagnostic memory-bank test through native SDRAM."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
from prepare import HERE, ROOT, BASE, WORK, sha, once, prepare

sys.path.insert(0, str(ROOT / 'fixtures/experiments/card-interrupt-contract'))
from test_interrupt_model import check_original
from host_model import load_conf_resources


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def originals(path):
    check_original(path)
    uploads = load_conf_resources(path)
    diagnostic = uploads[1001][6:]
    # The exact JSR and memory test remain original uploaded CPU instructions.
    assert diagnostic[0x43:0x46] == bytes.fromhex('209821')
    expected = bytes.fromhex(
        'a280a0808d09c08400ad2bc009108d2bc0c88400c400d02cad2bc029ef8d2bc0'
        '88c400d01f8d08c08c00b08d05c08d03c0c88c00b0cc00b0d00a8d04c08d02'
        'c088cc00b0d0602c8bc02c8bc08c00e0c88c00d02c83c02c83c0c88c00d08d'
        '09c0c88c00d02c8bc02c8bc0c88c00d0c88c00e0cc00e0d02f88cc00d0d029'
        '2c83c02c83c088cc00d0d01d8d08c088cc00d0d0142c8bc02c8bc088cc00d0'
        'd00888cc00e0d002a20060')
    assert diagnostic[0x198:0x23F] == expected
    parser_path = ROOT / 'fixtures/research/software-bringup/inspect_resources.py'
    spec = importlib.util.spec_from_file_location('banking_resources', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    raw = {(meta['type'], meta['id']): data for meta, data in parser.resources(path.read_bytes())}
    key = b'DoubleX'
    monitor = bytes(value ^ key[index % len(key)] for index, value in enumerate(raw['Monx', 2606]))[6:]
    assert hashlib.sha256(monitor).hexdigest() == 'c92e4db8d40298b759d756a23e51e8d99086cb625e4fbe8074c8c9b2a6bad554'
    return {'fork_sha256': sha(path), 'Conf_1001_payload_2198_223F_sha256': hashlib.sha256(expected).hexdigest(),
            'monitor_payload_sha256': hashlib.sha256(monitor).hexdigest()}


def main():
    closure = prepare()
    manifest_path = ROOT / 'fixtures/experiments/card-softswitch/results.json'
    manifest = json.loads(manifest_path.read_text())
    baseline_bench = BASE / 'tb_binding.sv'
    assert sha(baseline_bench) == manifest['inputs_sha256'][str(baseline_bench)], 'stale softswitch bench'
    bench = once(baseline_bench.read_text(), "card_cpu_address != 16'h2043", "card_cpu_address != 16'h2046")
    bench = once(bench, 'stores != 1208', 'stores != 1220')
    bench = once(bench, "!= 8'h42", "!= 8'h45")
    bench = once(bench, '        repeat (600) @(negedge clk_sys);', '''        i = 0;
        while (!boundary && i < 20000) begin
            @(negedge clk_sys);
            i = i + 1;
        end''')
    bench = once(bench, '        if (capture_valid || capture_count != 62)',
                "        if (dut.platform.card.card.processor.cpu.reg_x !== 8'h00)\n"
                '            $fatal(1, "original CPU banking test failed X=%h", dut.platform.card.card.processor.cpu.reg_x);\n'
                '        if (capture_valid || capture_count != 62)')
    bench = once(bench, '    always @(posedge clk_sys) begin\n        ticks = ticks + 1;', '''    wire negative_case = $test$plusargs("expect_banking_failure");
    always @(posedge clk_sys) begin
        if (negative_case && dut.platform.card.card.cpu_valid &&
            dut.platform.card.card.cpu_sync && card_cpu_address == 16'h223E &&
            dut.platform.card.card.processor.cpu.reg_x == 8'h80)
            $fatal(1, "original CPU banking test failed X=80 at RTS 223E");
        ticks = ticks + 1;''')
    bench = bench.replace('softswitch JSR stack mismatch', 'memory-bank JSR stack mismatch')
    bench = bench.replace('before the softswitch test.', 'before the memory-bank test.')
    bench_path = WORK / 'tb_binding.sv'
    bench_path.write_text(bench, encoding='ascii')
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    sources = [bench_path, binding, *closure, controller]
    executable = WORK / 'memory-banking.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
         '-o', linux(executable), *map(linux, sources)])
    runs, evidence = [], []
    inputs = [Path(__file__), HERE / 'prepare.py', manifest_path, baseline_bench, *sources]
    trace_prefix = BASE / 'captures-0-2.txt'
    assert sha(trace_prefix) == manifest['runs'][0]['capture_sha256'], 'stale capture trace'
    expected_captures = [tuple(int(value, 16) for value in row.split()) for row in trace_prefix.read_text().splitlines()]
    inputs.append(trace_prefix)
    forks = [ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc',
             ROOT / 'local/experiments/startup-runtime/startup/IIe Startup.rsrc']
    for fork, resource in enumerate(forks):
        evidence.append(originals(resource))
        prefix, old_image = BASE / f'stimulus{fork}.txt', BASE / f'expected{fork}.hex'
        inputs += [resource, prefix, old_image]
        stimulus = WORK / f'stimulus{fork}.txt'
        stimulus.write_bytes(prefix.read_bytes())
        expected = [int(value, 16) for value in old_image.read_text().split()]
        assert len(expected) == 262144 and expected[0x1FC] == 0x42 and expected[0x30000] == 0
        changes = {0x1FC: 0x45, 0x10000: 0x80, 0x30000: 0x81, 0xB000: 0x80, 0x1B000: 0x81,
                   0xE000: 0x80, 0xC000: 0x81, 0xD000: 0x82, 0x1D000: 0x83, 0x1C000: 0x84, 0x1E000: 0x85}
        for address, value in changes.items():
            expected[address] = value
        image = WORK / f'expected{fork}.hex'
        image.write_text(''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
        for phase in (2, 7):
            trace = WORK / f'captures-{fork}-{phase}.txt'
            output, errors = wsl(['vvp', linux(executable), '+stimulus=' + linux(stimulus),
                                  '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={phase}'])
            assert not errors and 'PASS PDS=' in output, output + errors
            assert [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()] == expected_captures
            print(output, flush=True)
            runs.append({'fork': fork, 'phase_ns': phase, 'result': output, 'capture_sha256': sha(trace)})
    wrapper = ROOT / 'local/experiments/maclc-iie-irq-build/card_pds_candidate.sv'
    controls = []
    for parameter in ('IGNORE_ZP_CONTEXT', 'ALIAS_LC_BANKS'):
        broken = WORK / (parameter.lower() + '.sv')
        broken.write_text(once(wrapper.read_text(), '    card_irq_candidate card (',
                               f'    card_irq_candidate #(.{parameter}(1)) card ('), encoding='ascii')
        executable = WORK / (parameter.lower() + '.vvp')
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(executable),
             *map(linux, [broken if path == wrapper else path for path in sources])])
        result = subprocess.run(['wsl', '--', 'vvp', linux(executable),
                                 '+stimulus=' + linux(WORK / 'stimulus0.txt'),
                                 '+expected=' + linux(WORK / 'expected0.hex'),
                                 '+trace=' + linux(WORK / (parameter.lower() + '-captures.txt')),
                                 '+expect_banking_failure'],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'original CPU banking test failed X=80 at RTS 223E' in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'parameter': parameter, 'result': result.stdout.strip()})
        print('PASS ' + parameter + ' fails original CPU banking test', flush=True)
    _, errors = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                     '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                     'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert '%Warning' not in errors, errors
    inputs += [ROOT / 'fixtures/experiments/card-softswitch/prepare.py',
               ROOT / 'fixtures/experiments/card-banking-system/prepare.py',
               ROOT / 'fixtures/experiments/card-irq-system/prepare.py',
               ROOT / 'fixtures/experiments/card-interrupt-contract/test_interrupt_model.py',
               ROOT / 'fixtures/experiments/host-harness/host_model.py',
               ROOT / 'fixtures/research/software-bringup/inspect_resources.py']
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'bounded original CPU memory-bank test through native SDRAM; no hardware claim',
        'boundary': '2046', 'runs': runs, 'original_spans': evidence, 'negative_controls': controls,
        'alternate_aux_zero_page_candidate_byte': '30000', 'memory_bytes_compared': 262144,
        'lint': 'binding/card closure -Wall passes with filename/unused exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
