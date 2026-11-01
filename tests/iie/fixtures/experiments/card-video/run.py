#!/usr/bin/env python3
"""Bounded RTL access sweeps against enumerated address sets."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-video'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr, result.stderr
    return result.stdout.strip()


def visible(base, length):
    # Each 128-byte block has 120 visible bytes and eight screen holes.
    return {base + block + column
            for block in range(0, length, 128) for column in range(120)}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    rtl = HERE / 'card_trap_decode.sv'
    bench = HERE / 'tb_card_trap_decode.sv'
    binary = WORK / 'decode.vvp'
    compiler = wsl(['iverilog', '-V']).splitlines()[0]
    wsl(['iverilog', '-g2012', '-s', 'tb_card_trap_decode', '-o', linux(binary),
         linux(rtl), linux(bench)])
    both = set(range(0xC050, 0xC060)) | {0xC070, 0xC0E8, 0xC0E9, 0xCFFF}
    both |= set(range(0xC090, 0xC0E0)) | set(range(0xC0F0, 0xC100))
    writes = both | {0xC000, 0xC001, 0xC00C, 0xC00D, 0xC00E, 0xC00F}
    text = {1: visible(0x400, 0x400), 2: visible(0x800, 0x400)}
    hires = {1: visible(0x2000, 0x2000), 2: visible(0x4000, 0x2000)}
    # Explicit page/mode expectations; no softswitch decoding is assumed.
    profiles = [
        ('off', 0x00, set(), set()),
        ('text1', 0x80, text[1], set()),
        ('text2', 0xC0, text[2], set()),
        ('text1_80col', 0x88, text[1], text[1]),
        ('text2_80col', 0xC8, text[2], text[2]),
        ('aux_text_full_graphics', 0x8C, text[1], set()),
        ('hires1', 0x20, hires[1], set()),
        ('hires2', 0x30, hires[2], set()),
        ('double_hires1', 0x22, hires[1], hires[1]),
        ('double_hires2', 0x32, hires[2], hires[2]),
        ('mixed_pages', 0xEA, text[2] | hires[1], text[2] | hires[1]),
        ('full_graphics_double_hires', 0xAE, text[1] | hires[1], hires[1]),
        ('motor_off', 0xAA, text[1] | hires[1], text[1] | hires[1]),
        ('motor_on', 0xAB, set(), set()),
    ]
    results = []
    for name, mode, main, aux in profiles:
        expected = [int(a in main) | (int(a in aux) << 1) |
                    (int(a in both) << 2) | (int(a in writes) << 3)
                    for a in range(65536)]
        image = WORK / (name + '.hex')
        image.write_text(''.join(f'{value:x}\n' for value in expected), encoding='ascii')
        output = wsl(['vvp', linux(binary), '+image=' + linux(image), f'+mode={mode:02x}'])
        output = output.splitlines()[0]
        assert output.startswith(f'PASS mode={mode:02x} '), output
        print(output, flush=True)
        results.append({'profile': name, 'mode': f'{mode:02x}', 'result': output,
                        'expected_sha256': sha(image)})
    wsl(['verilator', '--lint-only', '-Wall', '--top-module', 'card_trap_decode', linux(rtl)])
    manifest = {'compiler': compiler, 'runs': results,
                'accesses': len(profiles) * 65536 * 4,
                'invalid_checks': len(profiles) * 65536 * 4,
                'lint': 'PASS verilator --lint-only -Wall',
                'inputs_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p)
                                  for p in (Path(__file__), rtl, bench,
                                            ROOT / 'fixtures/experiments/trap-model/trap_model.py',
                                            ROOT / 'fixtures/research/card-architecture/REPORT.md')}}
    (HERE / 'results.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
