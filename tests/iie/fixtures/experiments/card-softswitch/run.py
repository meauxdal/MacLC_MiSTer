#!/usr/bin/env python3
"""Exercise original display-softswitch stores through native SDRAM."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from prepare import HERE, ROOT, BASE, WORK, ON, OFF, once, prepare, sha

sys.path.insert(0, str(ROOT / 'fixtures/experiments/card-interrupt-contract'))
from test_interrupt_model import check_original


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def originals(path):
    check_original(path)
    from host_model import load_conf_resources
    parser_path = ROOT / 'fixtures/research/software-bringup/inspect_resources.py'
    import importlib.util
    spec = importlib.util.spec_from_file_location('softswitch_resources', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    raw = {(meta['type'], meta['id']): data for meta, data in parser.resources(path.read_bytes())}
    conf = raw['Conf', 1000]
    assert conf[0x300:0x33A].hex() == (
        '7807422c000c610002dc4a40662651ccfff20c2c00ff0008661a7807422c000c'
        '610002c24a40660c51ccfff20c2c000000086704303c000f4e75')
    upload = load_conf_resources(path)[1001][6:]
    expected = b''.join(bytes((0x8D, address & 255, address >> 8)) for address in ON + OFF) + b'\x60'
    assert upload[0xC5:0xF6] == expected
    return {'fork_sha256': sha(path),
            'Conf_1000_0300_033A_sha256': hashlib.sha256(conf[0x300:0x33A]).hexdigest(),
            'Conf_1001_payload_20C5_20F6_sha256': hashlib.sha256(expected).hexdigest()}


def main():
    closure = prepare()
    manifest_path = ROOT / 'fixtures/experiments/maclc-iie-banking-build/binding-results.json'
    manifest = json.loads(manifest_path.read_text())
    frozen = [BASE / 'tb_binding.sv', BASE / 'maclc_iie_binding.sv', BASE / 'card_irq_candidate.sv']
    for path in frozen:
        assert sha(path) == manifest['inputs_sha256'][str(path)], 'stale banking source: ' + str(path)
    bench = once(frozen[0].read_text(), "card_cpu_address != 16'h2040", "card_cpu_address != 16'h2043")
    bench = once(bench, 'capture_count != 46', 'capture_count != 62')
    bench = once(bench, 'stores != 1206', 'stores != 1208')
    bench = once(bench, "!= 8'h3F", "!= 8'h42")
    bench = bench.replace('protection JSR stack mismatch', 'softswitch JSR stack mismatch')
    bench = bench.replace('before the protection test.', 'before the softswitch test.')
    bench = once(bench, '    always @(posedge clk_sys) begin\n        ticks = ticks + 1;', '''    reg held_switch = 0;
    reg [7:0] held_switches;
    reg [15:0] held_switch_address;
    always @(posedge clk_sys) begin
        if (capture_valid && dut.platform.card.card.display_switch &&
            !dut.platform.card.card.permitted) begin
            if (held_switch && held_switch_address == capture_address &&
                held_switches !== dut.platform.card.card.display_switches)
                $fatal(1, "softswitch status changed while held");
            held_switch <= 1;
            held_switch_address <= capture_address;
            held_switches <= dut.platform.card.card.display_switches;
        end else held_switch <= 0;
    end
    always @(posedge clk_sys) begin
        ticks = ticks + 1;''')
    bench_path = WORK / 'tb_binding.sv'
    bench_path.write_text(bench, encoding='ascii')
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    sources = [bench_path, frozen[1], *closure, controller]
    executable = WORK / 'softswitch.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
         '-o', linux(executable), *map(linux, sources)])
    runs, evidence, inputs = [], [], [Path(__file__), HERE / 'prepare.py', manifest_path, *frozen, *sources]
    baseline_trace = BASE / 'captures-0-2.txt'
    assert sha(baseline_trace) == manifest['runs'][0]['capture_sha256'], 'stale banking capture trace'
    prefix_captures = [tuple(int(value, 16) for value in row.split())
                       for row in baseline_trace.read_text().splitlines()]
    assert len(prefix_captures) == 46
    expected_captures = prefix_captures + [(0x08, address, 0) for address in ON + OFF]
    inputs.append(baseline_trace)
    forks = [ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc',
             ROOT / 'local/experiments/startup-runtime/startup/IIe Startup.rsrc']
    for fork, resource in enumerate(forks):
        evidence.append(originals(resource))
        prefix, old_image = BASE / f'stimulus{fork}.txt', BASE / f'expected{fork}.hex'
        inputs += [resource, prefix, old_image]
        tail = []
        for index, address in enumerate(ON + OFF):
            # Conf $5E4 polls twice; extra reads verify every held transition.
            state = (1 << (index + 1)) - 1 if index < 8 else 255 ^ ((1 << (index - 7)) - 1)
            tail += [(0, 0, 1, 8), (0, 0, 1, 8), (0, 1, 4, address),
                     (0, 0, 8, state), (0, 0, 8, state), (1, 0, 12, 0)]
        stimulus = WORK / f'stimulus{fork}.txt'
        stimulus.write_text(prefix.read_text() + ''.join(
            f'{write} {word} {offset} {value} 2000\n' for write, word, offset, value in tail), encoding='ascii')
        expected = [int(value, 16) for value in old_image.read_text().split()]
        assert len(expected) == 262144 and expected[0x1FC] == 0x3F
        expected[0x1FC] = 0x42
        image = WORK / f'expected{fork}.hex'
        image.write_text(''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
        for phase in (2, 7):
            trace = WORK / f'captures-{fork}-{phase}.txt'
            output, errors = wsl(['vvp', linux(executable), '+stimulus=' + linux(stimulus),
                                  '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={phase}'])
            assert not errors and 'PASS PDS=' in output, output + errors
            observed = [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()]
            assert observed == expected_captures, observed[46:]
            print(output, flush=True)
            runs.append({'fork': fork, 'phase_ns': phase, 'result': output, 'capture_sha256': sha(trace)})
    # Conf $300 tests only the aggregate after eight captures in each group.
    tail = []
    for index in range(16):
        tail += [(0, 1, 8), (0, 1, 8)]
        if index in (7, 15):
            tail.append((0, 8, 255 if index == 7 else 0))
        tail.append((1, 12, 0))
    conf_stimulus = WORK / 'conf-stimulus0.txt'
    conf_stimulus.write_text((BASE / 'stimulus0.txt').read_text() + ''.join(
        f'{write} 0 {offset} {value} 2000\n' for write, offset, value in tail), encoding='ascii')
    trace = WORK / 'conf-captures.txt'
    conf_result, errors = wsl(['vvp', linux(executable), '+stimulus=' + linux(conf_stimulus),
                               '+expected=' + linux(WORK / 'expected0.hex'), '+trace=' + linux(trace)])
    assert not errors and 'PASS PDS=' in conf_result, conf_result + errors
    assert [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()] == expected_captures
    print('PASS original Conf aggregate traffic\n' + conf_result, flush=True)
    wrapper = ROOT / 'local/experiments/maclc-iie-irq-build/card_pds_candidate.sv'
    controls = []
    for name, parameter, actual in [('frozen', '.IGNORE_SOFTSWITCH(1)', '00ff'),
                                     ('one_bit', ".SOFTSWITCH_STUCK_MASK(8'h80)", '7fff')]:
        broken = WORK / f'{name}.sv'
        broken.write_text(once(wrapper.read_text(), '    card_irq_candidate card (',
                               f'    card_irq_candidate #({parameter}) card ('), encoding='ascii')
        broken_sources = [broken if path == wrapper else path for path in sources]
        broken_executable = WORK / f'{name}.vvp'
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
             '-o', linux(broken_executable), *map(linux, broken_sources)])
        result = subprocess.run(['wsl', '--', 'vvp', linux(broken_executable),
                                 '+stimulus=' + linux(conf_stimulus),
                                 '+expected=' + linux(WORK / 'expected0.hex'),
                                 '+trace=' + linux(WORK / f'{name}-captures.txt')],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'offset=00000008 expected=ffff actual=' + actual in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'parameter': parameter, 'result': result.stdout.strip()})
        print('PASS ' + name + ' fails original Conf aggregate FF check', flush=True)
    _, errors = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                     '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                     'maclc_iie_binding', linux(frozen[1]), *map(linux, closure)])
    assert '%Warning' not in errors, errors
    inputs += [ROOT / 'fixtures/experiments/card-banking-system/prepare.py',
               ROOT / 'fixtures/experiments/card-irq-system/prepare.py',
               ROOT / 'fixtures/experiments/card-interrupt-contract/test_interrupt_model.py',
               ROOT / 'fixtures/experiments/host-harness/host_model.py',
               ROOT / 'fixtures/research/software-bringup/inspect_resources.py',
               conf_stimulus]
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'bounded display-softswitch candidate through actual CPU/native SDRAM; no hardware claim',
        'boundary': '2043', 'runs': runs, 'original_spans': evidence, 'negative_controls': controls,
        'original_conf_aggregate_run': conf_result,
        'memory_bytes_compared': 262144, 'lint': 'binding/card closure -Wall passes with filename/unused exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
