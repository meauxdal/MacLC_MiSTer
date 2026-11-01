#!/usr/bin/env python3
"""Exercise completed display switch state and resolved whole-page traps."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-state'


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
    return {base + block + column
            for block in range(0, length, 128) for column in range(120)}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'local/Apple-II_MiSTer/Apple-II_MiSTer-master.zip'
    with zipfile.ZipFile(archive) as source:
        timing_path = 'Apple-II_MiSTer-master/rtl/timing_generator.v'
        timing = source.read(timing_path)
    assert b'PAGE2 &  ~STORE80' in timing
    probes = [
        0x0000, 0x03FF, 0x0400, 0x0477, 0x0478, 0x047F, 0x0480, 0x07F7,
        0x07F8, 0x07FF, 0x0800, 0x0877, 0x0878, 0x0BF7, 0x0BF8, 0x0BFF,
        0x0C00, 0x1FFF, 0x2000, 0x2077, 0x2078, 0x207F, 0x2080, 0x3FF7,
        0x3FF8, 0x3FFF, 0x4000, 0x4077, 0x4078, 0x407F, 0x4080, 0x5FF7,
        0x5FF8, 0x5FFF, 0x6000, 0xBFFF, 0xC000, 0xC001, 0xC00C, 0xC00D,
        0xC00E, 0xC00F, 0xC04F, 0xC050, 0xC051, 0xC053, 0xC055, 0xC057,
        0xC05E, 0xC05F, 0xC060, 0xC070, 0xC080, 0xC090, 0xC0DF, 0xC0E7,
        0xC0E8, 0xC0E9, 0xC0EA, 0xC0F0, 0xC0FF, 0xCFFE, 0xCFFF, 0xFFFF,
    ]
    assert len(probes) == 64 and len(set(probes)) == 64
    io_both = set(range(0xC050, 0xC060)) | {0xC070, 0xC0E8, 0xC0E9, 0xCFFF}
    io_both |= set(range(0xC090, 0xC0E0)) | set(range(0xC0F0, 0xC100))
    io_writes = io_both | {0xC000, 0xC001, 0xC00C, 0xC00D, 0xC00E, 0xC00F}
    # TEXT, MIXED, HIRES -> whole text-memory page, HiRes page, full graphics.
    modes = {
        (0, 0, 0): (1, 0, 1), (0, 0, 1): (0, 1, 1),
        (0, 1, 0): (1, 0, 0), (0, 1, 1): (1, 1, 0),
        (1, 0, 0): (1, 0, 0), (1, 0, 1): (1, 0, 0),
        (1, 1, 0): (1, 0, 0), (1, 1, 1): (1, 0, 0),
    }
    text = {1: visible(0x400, 0x400), 2: visible(0x800, 0x400)}
    hires = {1: visible(0x2000, 0x2000), 2: visible(0x4000, 0x2000)}
    oracle, plans = [], []
    for state in range(256):
        text_mode, mixed, hires_mode = (state >> 1) & 1, (state >> 5) & 1, (state >> 2) & 1
        text_on, hires_on, full_graphics = modes[text_mode, mixed, hires_mode]
        col80 = bool(state & 0x10)
        # Explicit truth table for PAGE2, 80STORE, independently of bank selection.
        display_page = {(0, 0): 1, (0, 1): 1, (1, 0): 2, (1, 1): 1}[
            (state >> 6) & 1, (state >> 7) & 1]
        plans.append(text_on | (hires_on << 1) | ((display_page - 1) << 2))
        main = (text[display_page] if text_on else set()) | (hires[display_page] if hires_on else set())
        for double_hires in (False, True):
            aux = (set(text[display_page]) if text_on and col80 and not full_graphics else set())
            aux |= hires[display_page] if hires_on and double_hires else set()
            for motor in (False, True):
                for bank_set in (main, aux):
                    for write in (False, True):
                        for address in probes:
                            display = write and not motor and address in bank_set
                            io = address in (io_writes if write else io_both)
                            oracle.append(int(display) | (int(io) << 1))
    assert len(oracle) == 262144
    oracle_path, plans_path, probes_path = (WORK / name for name in ('oracle.hex', 'plans.hex', 'probes.hex'))
    for path, values in ((oracle_path, oracle), (plans_path, plans), (probes_path, probes)):
        path.write_text(''.join(f'{value:x}\n' for value in values), encoding='ascii')
    state_rtl = HERE / 'card_display_state.sv'
    bench = HERE / 'tb_card_display_state.sv'
    decoder = ROOT / 'fixtures/experiments/card-video/card_trap_decode.sv'
    binary = WORK / 'display.vvp'
    wsl(['iverilog', '-g2012', '-s', 'tb_card_display_state', '-o', linux(binary),
         linux(bench), linux(state_rtl), linux(decoder)])
    output = wsl(['vvp', linux(binary), '+oracle=' + linux(oracle_path),
                  '+plans=' + linux(plans_path), '+probes=' + linux(probes_path)])
    assert output.startswith('PASS states=256 '), output
    print(output, flush=True)
    wsl(['verilator', '--lint-only', '-Wall', '--top-module', 'card_display_state',
         linux(state_rtl), linux(decoder)])
    controls = []
    for name, old, new, marker in (
            ('ignore_80store', 'page2 && !store80', 'page2', 'page plan mode='),
            ('early_state', 'valid && complete', 'valid', 'state expected=')):
        text = state_rtl.read_text()
        assert text.count(old) == 1
        broken = WORK / (name + '.sv')
        broken.write_text(text.replace(old, new), encoding='ascii')
        executable = WORK / (name + '.vvp')
        wsl(['iverilog', '-g2012', '-s', 'tb_card_display_state', '-o', linux(executable),
             linux(bench), linux(broken), linux(decoder)])
        result = subprocess.run(['wsl', '--', 'vvp', linux(executable),
                                 '+oracle=' + linux(oracle_path), '+plans=' + linux(plans_path),
                                 '+probes=' + linux(probes_path)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and marker in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'name': name, 'failure': result.stdout.splitlines()[0]})
    inputs = [Path(__file__), state_rtl, bench, decoder,
              ROOT / 'local/experiments/card-cpu-rtl/source/apple2.v',
              ROOT / 'fixtures/experiments/card-softswitch/prepare.py',
              ROOT / 'fixtures/experiments/card-softswitch/REPORT.md']
    manifest = {
        'result': output.splitlines()[0], 'lint': 'PASS verilator --lint-only -Wall',
        'negative_controls': controls,
        'archive_sha256': sha(archive),
        'timing_archive_member': timing_path,
        'timing_source_sha256': hashlib.sha256(timing).hexdigest(),
        'inputs_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in inputs},
        'vectors_sha256': {p.name: sha(p) for p in (oracle_path, plans_path, probes_path)},
    }
    (HERE / 'results.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
