#!/usr/bin/env python3
"""Bounded cycle-pacing checks against frozen CPU and diagnostic inputs."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-cpu-pacing'
CPU = ROOT / 'fixtures/experiments/card-cpu-rtl'
SOURCE = ROOT / 'local/experiments/card-cpu-rtl/source'
sys.path.insert(0, str(CPU))
from run import expected_events
from host_model import HostStream, Hypothesis, conf_uploads, load_conf_resources


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    inputs = [Path(__file__), CPU / 'run.py', CPU / 'card_cpu_bus.sv', CPU / 'tb_diagnostic.sv',
              SOURCE / 'cpu_65c02.sv', SOURCE / 'cpu_alu.sv', CPU / 'results.json']
    pins = json.loads((CPU / 'results.json').read_text())['inputs_sha256']
    for path in inputs[2:6]:
        key = ('archive:rtl/cpu/wdc65c02/' + path.name if path.parent == SOURCE
               else path.relative_to(ROOT).as_posix())
        assert sha(path) == pins[key], 'changed frozen input: ' + str(path)
    WORK.mkdir(parents=True, exist_ok=True)
    sources = [HERE / 'card_cycle_pacer.sv', HERE / 'card_paced_cpu_bus.sv',
               CPU / 'card_cpu_bus.sv', SOURCE / 'cpu_65c02.sv', SOURCE / 'cpu_alu.sv']
    tests = []
    for name in ('tb_pacer', 'tb_response_reset'):
        bench = HERE / (name + '.sv')
        binary = WORK / (name + '.vvp')
        wsl(['iverilog', '-g2012', '-s', name, '-o', linux(binary), linux(bench), *map(linux, sources)])
        output, errors = wsl(['vvp', linux(binary)])
        assert output.startswith('PASS ') and not errors, output + errors
        print(output, flush=True)
        tests.append(output)
        inputs.append(bench)
    runs = []
    for fast in (0, 1):
        bench = (CPU / 'tb_diagnostic.sv').read_text()
        bench = bench.replace('always #5 clk = !clk;', 'always #7.692307 clk = !clk;')
        bench = bench.replace('card_cpu_bus dut (', 'card_paced_cpu_bus dut (')
        bench = bench.replace('.clk(clk), .reset(reset), .ready(ready),',
                              f'.clk(clk), .reset(reset), .fast(1\'b{fast}), .completed(), .ready(ready),')
        bench = bench.replace('dut.cpu.reg_s', 'dut.processor.cpu.reg_s')
        bench = bench.replace('end else ready = 0;', "end else begin ready = 0; data = 8'hFE; end")
        bench = bench.replace('endmodule', '''    integer last_complete = -1, min_gap = 100000, gap, pace_ticks = 0;
    reg [25:0] cpu_held;
    reg cpu_waiting = 0;
    always @(posedge clk) begin
        pace_ticks = pace_ticks + 1;
        if (reset) cpu_waiting = 0;
        else begin
            if (cpu_waiting && cpu_held !== {address, write_data, write, sync})
                $fatal(1, "CPU bus changed before paced completion");
            cpu_waiting = !dut.completed;
            cpu_held = {address, write_data, write, sync};
            if (dut.completed) begin
                if (last_complete >= 0) begin
                    gap = pace_ticks - last_complete;
                    if (gap < MIN_GAP) $fatal(1, "catch-up gap %0d", gap);
                    if (gap < min_gap) min_gap = gap;
                end
                last_complete = pace_ticks;
            end
        end
    end
endmodule'''.replace('MIN_GAP', str(65000000 // (1900000 if fast else 1020000))))
        path = WORK / f'tb_diagnostic{fast}.sv'
        path.write_text(bench, encoding='ascii')
        binary = WORK / f'diagnostic{fast}.vvp'
        wsl(['iverilog', '-g2012', '-s', 'tb_diagnostic', '-o', linux(binary), linux(path), *map(linux, sources)])
        for fork in (0, 1):
            image = ROOT / f'local/experiments/card-cpu-rtl/image{fork}.hex'
            resource = ROOT / ('local/experiments/startup-runtime/startup/IIe Startup.rsrc' if fork
                               else 'local/experiments/firmware-memory/app221/IIe Startup.rsrc')
            assert sha(resource) == pins[resource.relative_to(ROOT).as_posix()]
            stream = HostStream(Hypothesis('paced-cpu'), lambda offset, width: 0)
            assert conf_uploads(stream, load_conf_resources(resource)) == 0
            assert bytes(int(value, 16) for value in image.read_text().split()) == stream.memory
            inputs += [resource, image]
            for delay in (0, 1):
                trace = WORK / f'trace{fast}-{fork}-{delay}.txt'
                output, errors = wsl(['vvp', linux(binary), '+image=' + linux(image),
                                      '+trace=' + linux(trace), f'+delay={delay}'])
                assert output.startswith('PASS ') and not errors, output + errors
                observed = [tuple(int(v, 16) for v in row.split()) for row in trace.read_text().splitlines()]
                assert observed == expected_events(), observed
                print(f'fast={fast} fork={fork} delay={delay} {output}', flush=True)
                runs.append({'fast': fast, 'fork': fork, 'delay': delay, 'result': output,
                             'capture_sha256': sha(trace)})
    lint_out, lint_err = wsl(['verilator', '--lint-only', '-Wall', '-Wno-fatal',
                             '--top-module', 'card_paced_cpu_bus', *map(linux, sources)])
    warnings = re.findall(r'%Warning-([A-Z0-9_]+): ([^\n]+)', lint_err)
    assert all(kind in ('PINCONNECTEMPTY', 'DECLFILENAME') and
               ('/card-cpu-rtl/' in location) for kind, location in warnings), lint_err
    standalone_out, standalone_err = wsl(['verilator', '--lint-only', '-Wall',
                                         '--top-module', 'card_cycle_pacer', linux(sources[0])])
    assert not standalone_err, standalone_err
    (WORK / 'lint.txt').write_text(lint_out + lint_err, encoding='ascii')
    result = {'clock_hz': 65000000, 'normal_hz': 1020000, 'fast_hz': 1900000,
              'unit_tests': tests, 'runs': runs, 'full_memory_bytes_compared_per_run': 262144,
              'inputs_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [*inputs, *sources]},
              'lint': lint_err}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
