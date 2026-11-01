#!/usr/bin/env python3
"""Check the exact trial card closure on full LC addresses and native SDRAM."""
import argparse
import json
import shlex
import subprocess
from pathlib import Path
from prepare import HERE, ROOT, WORK, FINAL, once, prepare, sha


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(command):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fork', type=int, choices=(0, 1), required=True)
    parser.add_argument('--phase', type=int, choices=(2, 7), default=2)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    closure, binding = prepare()
    manifest_path = ROOT / 'fixtures/experiments/card-diagnostic-final/results.json'
    manifest = json.loads(manifest_path.read_text())
    source = FINAL / 'tb_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (source, controller):
        assert sha(path) == manifest['inputs_sha256'][str(path)]
    bench = once(source.read_text(), '    wire controller_ready;', '    wire controller_ready;\n    wire [199:0] debug_status;')
    assert "0: base = 32'hFE000000;" in bench and "1: base = 32'hFEE00000;" in bench
    bench = once(bench, '        $display("PASS final report consumed;', '''        if (debug_status[195:192] != {claim, capture_valid, diagnostic_boundary, diagnostic_fault} ||
            debug_status[191:176] != 16'h2052 || debug_status[175:160] != capture_address ||
            debug_status[159:152] != capture_status || debug_status[151:144] != capture_data ||
            debug_status[143:128] != card_cpu_address || debug_status[127:112] != capture_count[15:0] || debug_status[111:80] != cpu_completed ||
            debug_status[79:48] != transaction_count || debug_status[47:16] != pds_address ||
            debug_status[15:0] != 16'h0802)
            $fatal(1, "trial debug observation mismatch status=%h", debug_status);
        $display("PASS full LC address decode and debug counters");
        $display("PASS final report consumed;''')
    bench_path = WORK / 'tb_trial.sv'
    bench_path.write_text(bench, encoding='ascii')
    if args.control:
        path = WORK / 'iwm_control.sv'
        frontend = next(p for p in closure if p.name == 'card_iwm_frontend.sv')
        path.write_text(once(frontend.read_text(), 'mode <= write_data[4:0];', "mode <= 5'b0;"), encoding='ascii')
        closure = [path if p == frontend else p for p in closure]
    binary = WORK / 'trial-card.vvp'
    sources = [bench_path, binding, *closure, controller]
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary), *map(linux, sources)])
    stimulus = ROOT / f'local/experiments/card-firmware-overlay/stimulus{args.fork}.txt'
    image = FINAL / f'expected{args.fork}.hex'
    for path in (stimulus,):
        assert sha(path) == manifest['inputs_sha256'][str(path)]
    trace = WORK / f'{"control" if args.control else "captures"}-{args.fork}-{args.phase}.txt'
    result = subprocess.run(['wsl', '--exec', 'vvp', linux(binary), '+stimulus=' + linux(stimulus),
        '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={args.phase}'],
        capture_output=True, text=True, timeout=30)
    if args.control:
        assert result.returncode != 0 and 'original final diagnostic failed X=81' in result.stdout, result.stdout + result.stderr
    else:
        assert result.returncode == 0 and 'PASS full LC address decode' in result.stdout, result.stdout + result.stderr
        assert sha(trace) == manifest['runs'][0]['capture_sha256']
        wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
            '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module', 'maclc_iie_binding',
            linux(binding), *map(linux, closure)])
    record = {'fork': args.fork, 'phase_ns': args.phase, 'control': args.control,
        'result': result.stdout.strip(), 'capture_sha256': sha(trace),
        'scope': 'Assisted original final diagnostic with full LC addresses; actual trial closure; not unmodified hardware Startup',
        'inputs_sha256': {str(p): sha(p) for p in [HERE / 'check_card.py', *sources, manifest_path, stimulus, image]}}
    (HERE / f'{"control" if args.control else "card"}-{args.fork}-{args.phase}.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(result.stdout.strip())


if __name__ == '__main__':
    main()
