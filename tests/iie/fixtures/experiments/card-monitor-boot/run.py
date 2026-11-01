#!/usr/bin/env python3
"""Continue original monitor firmware to its boot-service report."""
import argparse
import hashlib
import json
import shlex
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-monitor-boot'
BASE = ROOT / 'local/experiments/card-monitor-resume'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fast', type=int, choices=(0, 1), default=1)
    parser.add_argument('--phase', type=int, choices=(2, 7), default=2)
    parser.add_argument('--control', action='store_true')
    parser.add_argument('--preserve-y', action='store_true')
    args = parser.parse_args()
    pins_path = ROOT / 'fixtures/experiments/card-monitor-resume/results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [Path(p) for p in names[names.index(str(binding)):] if Path(p).suffix in ('.v', '.sv')]
    sources.append(ROOT / 'fixtures/experiments/card-cpu-pacing/card_cycle_pacer.sv')
    original, image = BASE / 'tb_monitor.sv', BASE / 'initial.hex'
    for path in [original, image, *sources]:
        assert sha(path) == pins[str(path)], 'changed input: ' + str(path)
    WORK.mkdir(parents=True, exist_ok=True)
    closure = []
    for path in sources:
        if path.parent == BASE:
            target = WORK / path.name
            text = path.read_text()
            if path.name == 'card_irq_candidate.sv':
                text = once(text, '#(parameter FIXED_CX', '#(parameter BAD_BANNER = 0, parameter FIXED_CX')
                text = once(text, "monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFB63;",
                            "capture_valid && capture_address == 16'hC07D && capture_data == 2;")
                text = once(text, 'wire [17:0] physical =',
                            "wire [17:0] physical = BAD_BANNER && cpu_write && cpu_address == 16'h0416 ? 18'h00417 :")
            target.write_text(text, encoding='ascii')
            closure.append(target)
        else:
            closure.append(path)
    text = original.read_text()
    text = once(text, 'module tb_card_platform #(parameter FAST = 0);',
                'module tb_card_platform #(parameter FAST = 0, parameter BAD_BANNER = 0);')
    text = once(text, '    reg [7:0] text_expected [0:1023];',
                '    reg [7:0] text_expected [0:1023];\n    reg [7:0] banner_source [0:255];\n    integer source_address;')
    text = once(text, '    integer source_address;',
                '    integer source_address, preserve_y = 0, copy_count;')
    text = once(text, '        $readmemh(image_path, expected);',
                '        if ($value$plusargs("preserve_y=%d", preserve_y)) begin end\n'
                '        $readmemh(image_path, expected);')
    text = once(text, '    defparam dut.platform.card.card.PACE_FAST = FAST;',
                '    defparam dut.platform.card.card.PACE_FAST = FAST;\n'
                '    defparam dut.platform.card.card.BAD_BANNER = BAD_BANNER;')
    start = text.index('        wait(boundary);', text.index('normal monitor service contract mismatch'))
    end = text.index('        stop_competitors = 1;', start)
    text = text[:start] + (HERE / 'sequence.sv').read_text() + text[end:]
    text = once(text, 'capture_count != switch_services + 2 || capture_valid ||',
                'capture_count != switch_services + 1 + opcodes || !capture_valid ||')
    start = text.index('        for (i = 0; i < 1024; i = i + 1) begin', text.index('monitor memory transport mismatch'))
    end = text.index('        if (cx_reads == 0', start)
    text = text[:start] + text[end:]
    bench = WORK / 'tb_monitor.sv'
    bench.write_text(text, encoding='ascii')
    binary = WORK / f'monitor-{args.fast}.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
         f'-Ptb_card_platform.FAST={args.fast}', f'-Ptb_card_platform.BAD_BANNER={int(args.control)}',
         '-o', linux(binary), linux(bench), *map(linux, closure)])
    tag = f'{args.fast}-{args.phase}' + ('-control' if args.control else '')
    if args.preserve_y:
        tag += '-preserved-y'
    trace, instructions = WORK / f'captures-{tag}.txt', WORK / f'instructions-{tag}.txt'
    rejected = None
    try:
        output = wsl(['vvp', linux(binary), '+trace=' + linux(trace), '+image=' + linux(image),
                      '+instructions=' + linux(instructions), f'+sys_phase={args.phase}',
                      f'+preserve_y={int(args.preserve_y)}'])
    except AssertionError as error:
        if not args.control or 'original banner mismatch' not in str(error):
            print('\n'.join(instructions.read_text().splitlines()[-24:]), flush=True)
            raise
        output, rejected = str(error), 'original banner mismatch'
    assert rejected is not None if args.control else 'PASS monitor' in output
    print(output, flush=True)
    inputs = [pins_path, original, image, HERE / 'run.py', HERE / 'sequence.sv', *sources, bench, *closure]
    (HERE / f'results-{tag}.json').write_text(json.dumps({
        'scope': 'original monitor with harness ACKs and injected saved Y=9 unless preserved; candidate mapping',
        'fast': args.fast, 'phase_ns': args.phase, 'control': args.control,
        'saved_y_injected': not args.preserve_y,
        'rejected': rejected, 'result': output,
        'capture_sha256': sha(trace), 'instructions_sha256': sha(instructions),
        'inputs_sha256': {str(p): sha(p) for p in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
