#!/usr/bin/env python3
"""Check the hardware binding against original diagnostic traffic at LC clocks."""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
from prepare import HERE, ROOT, WORK, MACLC, prepare


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--existing-project', action='store_true', help='test generated sources without rewriting project settings')
    args = parser.parse_args()
    if args.existing_project:
        closure = [ROOT / name for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"',
                                                     (WORK / 'card_platform.qip').read_text())]
        assert len(closure) == 12 and all(path.is_file() for path in closure)
    else:
        closure = prepare()
    original_tb = HERE.parent / 'card-platform/tb_card_platform.sv'
    bench = original_tb.read_text().replace('dut.', 'dut.platform.')
    bench = bench.replace('integer sys_half = 7, sys_phase = 1;', 'real sys_half = 15.3845, sys_phase = 2;')
    bench = bench.replace('always #5 clk_mem', 'always #7.69225 clk_mem')
    bench = bench.replace('sys_half=%d', 'sys_half=%f').replace('sys_phase=%d', 'sys_phase=%f')
    bench = bench.replace('sys_half = 7;', 'sys_half = 15.3845;').replace('sys_phase = 1;', 'sys_phase = 2;')
    debug = ['fault', 'boundary', 'card_cpu_address', 'capture_valid', 'capture_status',
             'capture_address', 'capture_data', 'capture_count', 'cpu_completed']
    bench = bench.replace('    card_platform dut (.*);', '''    wire controller_ready;
    maclc_iie_binding dut (.pll_locked(por_n_mem), .memory_ready(controller_ready), .*);
''' + '\n'.join('    assign ' + name + ' = dut.platform.' + name + ';' for name in debug))
    bench = bench.replace('.init(init),', '.memory_ready(controller_ready), .init(init),')
    bench = bench.replace("0: base = 32'h80000000;", "0: base = 32'hFE000000;")
    bench = bench.replace("1: base = 32'h80E00000;", "1: base = 32'hFEE00000;")
    bench = bench.replace('        unsupported;', '''        unclaimed(32'hFE000024, 3'b001);
        unclaimed(32'hFEE00025, 3'b001);
        unclaimed(32'hFE000001, 3'b001);
        unclaimed(32'hFE000000, 3'b111);
        unclaimed(32'hFEE00000, 3'b111);
        unclaimed(32'hFD000000, 3'b001);
        unsupported;''')
    bench = bench.replace('        abort_accepted_read;', '''        abort_accepted_read;
        // LC ROM probe: four stream words advance the saved index by four.
        transact(0, 1, 28, 1, 0);
        transact(0, 1, 16, 0, 0);
        transact(0, 1, 28, 2, 0);
        transact(0, 1, 16, 0, 0);
        transact(0, 1, 16, 0, 0);
        transact(0, 1, 16, 0, 0);
        transact(0, 1, 28, 5, 0);''')
    bench = bench.replace('plus 5 unclaimed', 'plus 11 unclaimed')
    (WORK / 'tb_binding.sv').write_text(bench, encoding='ascii')
    sources = [WORK / 'tb_binding.sv', HERE / 'maclc_iie_binding.sv', *closure, WORK / 'sdram.v']
    binary = WORK / 'binding.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary), *map(linux, sources)])
    runs = []
    for fork in (0, 1):
        generated = ROOT / 'local/experiments/card-system-harness'
        stimulus = generated / ('stimulus' + str(fork) + '.txt')
        expected = generated / ('expected' + str(fork) + '.hex')
        assert stimulus.is_file() and expected.is_file(), 'missing original diagnostic stimulus'
        for phase in (2, 7):
            trace = WORK / ('captures-' + str(fork) + '-' + str(phase) + '.txt')
            output, errors = wsl(['vvp', linux(binary), '+stimulus=' + linux(stimulus),
                                  '+expected=' + linux(expected), '+trace=' + linux(trace), '+sys_phase=' + str(phase)])
            assert not errors and output.startswith('PASS '), output + errors
            digest = hashlib.sha256(trace.read_bytes()).hexdigest()
            assert digest == '77f7eb7ce43f16cb5d66b8491b8c1783e21a0259ee4551c784e6dbe8e1e45246'
            print(output, flush=True)
            runs.append({'fork': fork, 'phase_ns': phase, 'result': output, 'capture_sha256': digest})
    broken = WORK / 'binding-unmapped.sv'
    binding = (HERE / 'maclc_iie_binding.sv').read_text()
    assert binding.count('.pds_address(card_address)') == 1
    broken.write_text(binding.replace('.pds_address(card_address)', '.pds_address(pds_address)'), encoding='ascii')
    negative = WORK / 'binding-unmapped.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(negative),
         linux(sources[0]), linux(broken), *map(linux, sources[2:])])
    result = subprocess.run(['wsl', '--', 'vvp', linux(negative),
                             '+stimulus=' + linux(generated / 'stimulus0.txt'),
                             '+expected=' + linux(generated / 'expected0.hex'),
                             '+trace=' + linux(WORK / 'unmapped-captures.txt')],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'early claim' in result.stdout and not result.stderr, result.stdout + result.stderr
    unmapped_result = result.stdout.strip()
    print('PASS unmapped negative control: full-address ROM probe loses card claim', flush=True)
    _, err = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                  '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module', 'maclc_iie_binding',
                  linux(HERE / 'maclc_iie_binding.sv'), *map(linux, closure)])
    assert '%Warning' not in err, err
    top = (WORK / 'MacLC_IIe.sv').read_text(encoding='utf-8')
    statements = re.sub(r'//[^\n]*', '', top)
    extracted = []
    for signal in ('iie_card_claim', '_romOE', '_ramOE', '_ramWE', '_cpuVPA', '_cpuDTACK', 'cpu_berr', 'cpu_din_muxed'):
        pattern = r'(?:wire (?:\[15:0\] )?|assign\s+)' + re.escape(signal) + r' =.*?;'
        matches = re.findall(pattern, statements, re.S)
        assert len(matches) == 1, signal
        extracted.append(matches[0])
    for signal in ('cacheable', 'snoopable'):
        expression = re.findall(r'\.' + signal + r'\s*\( (.*?) \),', statements)
        assert len(expression) == 1, signal
        extracted.append('wire ' + signal + ' = ' + expression[0] + ';')
    template = (HERE / 'tb_seams.sv').read_text()
    seam_source = template.replace('// EXTRACTED', '\n'.join(extracted))
    seam_runs = []
    for name, text, marker in [
        ('seams', seam_source, None),
        ('overlay-mask', seam_source.replace('iie_rom_oe_raw || iie_card_claim', 'iie_rom_oe_raw'), 'claimed overlay strobes escaped'),
        ('dtack-priority', seam_source.replace("iie_card_claim ? (iie_card_error ? 1'b1 : iie_card_dtack_n) :", ''), 'card wait lost bus priority')]:
        path = WORK / (name + '.sv')
        path.write_text(text, encoding='ascii')
        executable = WORK / (name + '.vvp')
        wsl(['iverilog', '-g2012', '-s', 'tb_seams', '-o', linux(executable), linux(path)])
        result = subprocess.run(['wsl', '--', 'vvp', linux(executable)], capture_output=True, text=True, timeout=30)
        assert not result.stderr, result.stderr
        assert (result.returncode != 0 and marker in result.stdout) if marker else (result.returncode == 0 and 'PASS' in result.stdout), result.stdout
        print(result.stdout.strip(), flush=True)
        seam_runs.append({'name': name, 'expected_failure': marker, 'result': result.stdout.strip()})
    inputs = [original_tb, *sources, HERE / 'run.py', HERE / 'tb_seams.sv', WORK / 'seams.sv', WORK / 'MacLC_IIe.sv']
    (HERE / 'binding-results.json').write_text(json.dumps({
        'scope': 'hardware binding with full LC addresses, recovered ROM probe and original diagnostic traffic; modeled PDS and SDRAM chip',
        'system_period_ns': 30.769, 'memory_period_ns': 15.3845,
        'runs': runs, 'unmapped_negative_control': unmapped_result,
        'seam_checks': seam_runs, 'lint': 'binding and card closure -Wall passes with filename/unused exclusions',
        'inputs_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
