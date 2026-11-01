#!/usr/bin/env python3
"""Execute the unmodified firmware-overlay test using original vector bytes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile
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
    diagnostic = load_conf_resources(path)[1001][6:]
    expected = bytes.fromhex('a2822c82c0acfaffad2bc009808d28c0ccfafff00aad2bc029f78d2bc0a20060')
    assert diagnostic[0x143:0x163] == expected
    assert diagnostic[0x46:0x4F] == bytes.fromhex('8ad0092043218ad003')
    parser_path = ROOT / 'fixtures/research/software-bringup/inspect_resources.py'
    spec = importlib.util.spec_from_file_location('overlay_resources', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    raw = {(meta['type'], meta['id']): data for meta, data in parser.resources(path.read_bytes())}
    key = b'DoubleX'
    monitor = bytes(value ^ key[index % len(key)] for index, value in enumerate(raw['Monx', 2606]))[6:]
    assert hashlib.sha256(monitor).hexdigest() == 'c92e4db8d40298b759d756a23e51e8d99086cb625e4fbe8074c8c9b2a6bad554'
    vectors = monitor[0x3FFA:]
    assert vectors == bytes.fromhex('fb0362fafac3')
    return vectors, {'fork_sha256': sha(path), 'Conf_1001_payload_2143_2163_sha256': hashlib.sha256(expected).hexdigest(),
                     'monitor_payload_sha256': hashlib.sha256(monitor).hexdigest(),
                     'monitor_vectors_sha256': hashlib.sha256(vectors).hexdigest()}


def main():
    closure = prepare()
    archive = ROOT / 'local/Apple-II_MiSTer/Apple-II_MiSTer-master.zip'
    assert sha(archive) == 'c474744878f2e41865d08eccc8b1f4f7d2b3db6a34ba13d75f3424a839825a9d'
    with zipfile.ZipFile(archive) as source:
        assert source.comment.decode('ascii') == 'c701e64099d633a26cb1de002edfae07fb16a8fa'
        for name in ('cpu_65c02.sv', 'cpu_alu.sv'):
            actual = next(path for path in closure if path.name == name)
            assert actual.read_bytes() == source.read('Apple-II_MiSTer-master/rtl/cpu/wdc65c02/' + name)
        machine = source.read('Apple-II_MiSTer-master/rtl/apple2.v')
        assert b'assign rom_addr = A[13:0];' in machine
        assert b'C028' not in machine.upper() and b'C02B' not in machine.upper()
    manifest_path = ROOT / 'fixtures/experiments/card-memory-banking/results.json'
    manifest = json.loads(manifest_path.read_text())
    baseline_bench = BASE / 'tb_binding.sv'
    assert sha(baseline_bench) == manifest['inputs_sha256'][str(baseline_bench)], 'stale memory-banking bench'
    bench = once(baseline_bench.read_text(), "card_cpu_address != 16'h2046", "card_cpu_address != 16'h204F")
    bench = once(bench, 'stores != 1220', 'stores != 1228')
    bench = once(bench, "!= 8'h45", "!= 8'h4B")
    bench = bench.replace('memory-bank JSR stack mismatch', 'firmware-overlay JSR stack mismatch')
    bench = bench.replace('before the memory-bank test.', 'before the firmware-overlay test.')
    bench = once(bench, '    wire negative_case =', '''    wire overlay_negative = $test$plusargs("expect_overlay_failure");
    integer overlay_reads = 0;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.cpu_ready && !dut.platform.card.card.cpu_write &&
            !dut.platform.card.card.vector_pull && card_cpu_address == 16'hFFFA) begin
            if (overlay_reads == 0 && (dut.platform.card.card.physical !== 18'h23FFA ||
                dut.platform.card.card.cpu_rdata !== 8'h00))
                $fatal(1, "initial diagnostic vector source changed");
            if (overlay_reads == 1 && !overlay_negative &&
                (dut.platform.card.card.physical !== 18'h2FFFA || dut.platform.card.card.cpu_rdata !== 8'hFB))
                $fatal(1, "overlay did not return the original monitor vector through SDRAM");
            overlay_reads = overlay_reads + 1;
        end
        if (overlay_negative && dut.platform.card.card.cpu_valid &&
            dut.platform.card.card.cpu_sync && card_cpu_address == 16'h2162 &&
            dut.platform.card.card.processor.cpu.reg_x == 8'h82)
            $fatal(1, "original CPU overlay test failed X=82 at RTS 2162");
    end
    wire negative_case =''')
    bench = once(bench, '        stop_competitors = 1;', '''        if (overlay_reads != 2 || dut.platform.card.card.card_mode[3])
            $fatal(1, "overlay reads or original bit-3 clear missing");
        stop_competitors = 1;''')
    bench_path = WORK / 'tb_binding.sv'
    bench_path.write_text(bench, encoding='ascii')
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    sources = [bench_path, binding, *closure, controller]
    executable = WORK / 'firmware-overlay.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(executable), *map(linux, sources)])
    runs, evidence = [], []
    inputs = [Path(__file__), HERE / 'prepare.py', manifest_path, baseline_bench, archive, *sources]
    trace_prefix = BASE / 'captures-0-2.txt'
    assert sha(trace_prefix) == manifest['runs'][0]['capture_sha256'], 'stale capture trace'
    expected_captures = [tuple(int(value, 16) for value in row.split()) for row in trace_prefix.read_text().splitlines()]
    inputs.append(trace_prefix)
    forks = [ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc',
             ROOT / 'local/experiments/startup-runtime/startup/IIe Startup.rsrc']
    for fork, resource in enumerate(forks):
        vectors, proof = originals(resource)
        evidence.append(proof)
        prefix, old_image = BASE / f'stimulus{fork}.txt', BASE / f'expected{fork}.hex'
        inputs += [resource, prefix, old_image]
        # Additional candidate initialization, not the captured Conf sequence.
        preload = [(1, 0, 13, 8), (1, 1, 28, 0xFFFA)]
        preload += [(1, 0, 16, value) for value in vectors]
        preload += [(1, 1, 28, 0xFFFA)] + [(0, 0, 16, value) for value in vectors] + [(1, 0, 13, 0)]
        rows = ''.join(f'{write} {word} {offset} {value} 0\n' for write, word, offset, value in preload)
        marker = '1 0 33 252 0\n1 0 32 128 0\n'
        stimulus = WORK / f'stimulus{fork}.txt'
        stimulus.write_text(once(prefix.read_text(), marker, rows + marker), encoding='ascii')
        expected = [int(value, 16) for value in old_image.read_text().split()]
        assert len(expected) == 262144 and expected[0x1FC] == 0x45 and expected[0x2FFFA:0x30000] == [0] * 6
        expected[0x1FC] = 0x4B
        expected[0x2FFFA:0x30000] = vectors
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
    broken = WORK / 'ignore_overlay.sv'
    broken.write_text(once(wrapper.read_text(), '    card_irq_candidate card (',
                           '    card_irq_candidate #(.IGNORE_FW_OVERLAY(1)) card ('), encoding='ascii')
    executable = WORK / 'ignore_overlay.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(executable),
         *map(linux, [broken if path == wrapper else path for path in sources])])
    result = subprocess.run(['wsl', '--', 'vvp', linux(executable),
                             '+stimulus=' + linux(WORK / 'stimulus0.txt'),
                             '+expected=' + linux(WORK / 'expected0.hex'),
                             '+trace=' + linux(WORK / 'ignore-overlay-captures.txt'), '+expect_overlay_failure'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'original CPU overlay test failed X=82 at RTS 2162' in result.stdout and not result.stderr, result.stdout + result.stderr
    print('PASS ignored overlay takes the original X=82 failure path', flush=True)
    _, errors = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                     '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                     'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert '%Warning' not in errors, errors
    inputs += [ROOT / 'fixtures/experiments/card-memory-banking/prepare.py',
               ROOT / 'fixtures/experiments/card-softswitch/prepare.py', ROOT / 'fixtures/experiments/card-banking-system/prepare.py',
               ROOT / 'fixtures/experiments/card-irq-system/prepare.py', ROOT / 'fixtures/experiments/card-interrupt-contract/test_interrupt_model.py',
               ROOT / 'fixtures/experiments/host-harness/host_model.py', ROOT / 'fixtures/research/software-bringup/inspect_resources.py']
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'bounded original CPU overlay test with additional original monitor-vector preload; no hardware claim',
        'boundary': '204F', 'runs': runs, 'original_spans': evidence,
        'negative_control': result.stdout.strip(), 'candidate_monitor_vector_backing': '2FFFA-2FFFF',
        'memory_bytes_compared': 262144, 'archived_apple2_sha256': hashlib.sha256(machine).hexdigest(),
        'lint': 'binding/card closure -Wall passes with filename/unused exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
