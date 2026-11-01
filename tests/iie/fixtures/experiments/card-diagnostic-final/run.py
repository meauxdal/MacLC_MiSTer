#!/usr/bin/env python3
"""Reach the original final CPU report with explicit candidate host services."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from prepare import HERE, ROOT, BASE, WORK, once, prepare, sha


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    closure = prepare()
    manifest_path = ROOT / 'fixtures/experiments/card-firmware-overlay/results.json'
    manifest = json.loads(manifest_path.read_text())
    bench_source = BASE / 'tb_binding.sv'
    assert sha(bench_source) == manifest['inputs_sha256'][str(bench_source)]
    bench = once(bench_source.read_text(), '    task transact;', '    reg [7:0] last_read;\n    task transact;')
    bench = once(bench, '            if (write_arg == 0 && pds_read_data !== expected_data)',
                 '''            if (write_arg == 0) begin
                last_read = offset_arg[0] ? pds_read_data[7:0] : pds_read_data[15:8];
                if (value_arg == -1) expected_data = pds_read_data;
            end
            if (write_arg == 0 && pds_read_data !== expected_data)''')
    bench = once(bench, '    task unclaimed', '''    task wait_status(input [7:0] wanted);
        integer sample;
        begin : polling
            transact(0, 0, 1, -1, 0);
            for (sample = 0; sample < 1001; sample = sample + 1) begin
                transact(0, 0, 1, -1, 0);
                if (last_read != 0) begin
                    if (last_read !== wanted) $fatal(1, "unexpected final status %h", last_read);
                    disable polling;
                end
            end
            $fatal(1, "final status timeout expected=%h", wanted);
        end
    endtask

    task unclaimed''')
    start = bench.index('        i = 0;\n        while (!boundary')
    end = bench.index('        if (capture_valid || capture_count != 62)', start)
    bench = bench[:start] + '''        // Extra harness service: the frozen C0E8 trap remains enabled.
        wait_status(8'h28);
        transact(0, 1, 4, 16'hC0E8, 0);
        transact(1, 0, 12, 0, 0);
        wait_status(8'hE0);
        transact(0, 1, 4, 16'hC07D, 0);
        if (dut.platform.card.card.processor.cpu.reg_x !== 8'h00)
            $fatal(1, "original final diagnostic failed X=%h", dut.platform.card.card.processor.cpu.reg_x);
        transact(0, 0, 12, 0, 0);
        if (!capture_valid || card_cpu_address != 16'hC07D || capture_data != 0)
            $fatal(1, "final report was not retained after host data read");
        if (dut.platform.card.card.iwm_mode != 0 || dut.platform.card.card.iwm_motor ||
            !dut.platform.card.card.iwm_q6 || dut.platform.card.card.iwm_q7)
            $fatal(1, "final IWM mode/softswitch state mismatch");
''' + bench[end:]
    bench = once(bench, 'if (capture_valid || capture_count != 62)', 'if (!capture_valid || capture_count != 64)')
    bench = once(bench, 'if (!diagnostic_boundary || diagnostic_fault)', 'if (diagnostic_boundary || diagnostic_fault)')
    bench = once(bench, 'stores != 1228', 'stores != 1230')
    bench = once(bench, "!= 8'h4B", "!= 8'h51")
    bench = bench.replace('firmware-overlay JSR stack mismatch', 'final controller JSR stack mismatch')
    bench = bench.replace('before the firmware-overlay test.', 'before the controller test.')
    bench = once(bench, '        $fclose(stimulus);', '''        // Conf consumes the final byte, then issues this reset without ACK.
        transact(1, 1, 32, 16'h0802, 0);
        repeat (8) @(negedge clk_sys);
        if (dut.platform.card.card.cpu_running || capture_valid || fault ||
            dut.platform.card.card.cpu_memory_wait || dut.platform.card.card.iwm_mode != 0 ||
            dut.platform.card.card.iwm_motor || accepted != responses ||
            accepted != transaction_count + 2 || stores != 1230)
            $fatal(1, "final host reset failed to clear/drain card state");
        $display("PASS final report consumed; original word reset clears card/IWM state");
        $fclose(stimulus);''')
    bench_path = WORK / 'tb_binding.sv'
    bench_path.write_text(bench, encoding='ascii')
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (binding, controller):
        assert sha(path) == manifest['inputs_sha256'][str(path)]
    sources = [bench_path, binding, *closure, controller]
    binary = WORK / 'final.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary), *map(linux, sources)])
    prefix_trace = BASE / 'captures-0-2.txt'
    assert sha(prefix_trace) == manifest['runs'][0]['capture_sha256']
    captures = [tuple(int(value, 16) for value in row.split()) for row in prefix_trace.read_text().splitlines()]
    captures += [(0x28, 0xC0E8, 0), (0xE0, 0xC07D, 0)]
    runs, inputs = [], [__file__, HERE / 'prepare.py', manifest_path,
                        ROOT / 'fixtures/experiments/card-iwm/results.json', bench_source, prefix_trace, *sources]
    for fork in (0, 1):
        stimulus = BASE / f'stimulus{fork}.txt'
        old_image = BASE / f'expected{fork}.hex'
        memory_base = ROOT / 'local/experiments/card-memory-banking'
        prefix, memory_image = memory_base / f'stimulus{fork}.txt', memory_base / f'expected{fork}.hex'
        for path in (prefix, memory_image):
            assert sha(path) == manifest['inputs_sha256'][str(path)], 'changed frozen memory input'
        vectors = bytes.fromhex('fb0362fafac3')
        assert hashlib.sha256(vectors).hexdigest() == manifest['original_spans'][fork]['monitor_vectors_sha256']
        preload = [(1, 0, 13, 8), (1, 1, 28, 0xFFFA)]
        preload += [(1, 0, 16, value) for value in vectors]
        preload += [(1, 1, 28, 0xFFFA)] + [(0, 0, 16, value) for value in vectors] + [(1, 0, 13, 0)]
        rows = ''.join(f'{write} {word} {offset} {value} 0\n' for write, word, offset, value in preload)
        marker = '1 0 33 252 0\n1 0 32 128 0\n'
        assert stimulus.read_text() == once(prefix.read_text(), marker, rows + marker)
        expected = [int(value, 16) for value in old_image.read_text().split()]
        frozen = [int(value, 16) for value in memory_image.read_text().split()]
        assert len(frozen) == 262144 and frozen[0x1FC] == 0x45 and frozen[0x2FFFA:0x30000] == [0] * 6
        frozen[0x1FC] = 0x4B
        frozen[0x2FFFA:0x30000] = vectors
        assert expected == frozen, 'changed generated overlay memory image'
        expected[0x1FC] = 0x51
        image = WORK / f'expected{fork}.hex'
        image.write_text(''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
        inputs += [stimulus, old_image, prefix, memory_image]
        for phase in (2, 7):
            trace = WORK / f'captures-{fork}-{phase}.txt'
            output, errors = wsl(['vvp', linux(binary), '+stimulus=' + linux(stimulus),
                                  '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={phase}'])
            assert not errors and 'PASS final report consumed' in output, output + errors
            assert [tuple(int(v, 16) for v in row.split()) for row in trace.read_text().splitlines()] == captures
            print(output, flush=True)
            runs.append({'fork': fork, 'phase_ns': phase, 'result': output, 'capture_sha256': sha(trace)})
    frontend = ROOT / 'fixtures/experiments/card-iwm/card_iwm_frontend.sv'
    broken = WORK / 'frozen_iwm_mode.sv'
    broken.write_text(once(frontend.read_text(), 'mode <= write_data[4:0];', "mode <= 5'b0;"), encoding='ascii')
    bad_binary = WORK / 'frozen-mode.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(bad_binary),
         *map(linux, [broken if p == frontend else p for p in sources])])
    result = subprocess.run(['wsl', '--', 'vvp', linux(bad_binary),
                             '+stimulus=' + linux(BASE / 'stimulus0.txt'),
                             '+expected=' + linux(WORK / 'expected0.hex'),
                             '+trace=' + linux(WORK / 'frozen-mode-captures.txt')],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'original final diagnostic failed X=81' in result.stdout and not result.stderr, result.stdout + result.stderr
    _, warnings = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                       '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                       'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert '%Warning' not in warnings, warnings
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'original CPU diagnostic final report; candidate preload and extra C0E8 service; no full Startup claim',
        'runs': runs, 'negative_control': result.stdout.strip(), 'memory_bytes_compared': 262144,
        'lint': 'binding/card closure passes with existing filename/unused/empty exclusions',
        'inputs_sha256': {str(p): sha(p) for p in map(Path, inputs)}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
