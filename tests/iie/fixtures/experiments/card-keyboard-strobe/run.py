#!/usr/bin/env python3
"""Check an isolated keyboard latch and pin original host/firmware evidence."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-keyboard-strobe'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    firmware = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    data = firmware.read_bytes()
    windows = {0xC298: 'ad00c08d10c030c4', 0xC846: '8d10c060',
               0xFA7E: '2c10c0', 0xFB85: '2c10c0', 0xFB91: '2c10c0'}
    for address, expected in windows.items():
        assert data[address - 0xC000:address - 0xC000 + len(expected) // 2].hex() == expected
    host_paths = [ROOT / f'local/experiments/firmware-memory/CODE_{driver}.txt'
                  for driver in (5, 6)]
    binaries = [ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
                for driver in (5, 6)]
    for path in binaries:
        original = path.read_bytes()
        assert original[0x2480:0x2488].hex() == '082c000700096620'
        assert original[0x2496:0x249e].hex() == '19750520f6970018'
        assert original[0x2730:0x2734].hex() == '19410018'
    for path in host_paths:
        text = path.read_text()
        assert '2480: 082c 0007 0009' in text
        assert '2496: 1975 0520 f697 0018' in text
        assert '2730: 1941 0018' in text
    sources = [HERE / 'card_keyboard_candidate.sv', HERE / 'tb_keyboard.sv']
    executable = WORK / 'keyboard.vvp'
    wsl(['iverilog', '-g2012', '-s', 'tb_keyboard', '-o', linux(executable),
         *map(linux, sources)])
    output = wsl(['vvp', linux(executable)])
    assert output.startswith('PASS '), output
    lint = wsl(['verilator', '--lint-only', '-Wall', '--top-module',
                'card_keyboard_candidate', linux(sources[0])])
    controls = {}
    for name, old, new in [('missing_strobe', "{1'b1, host_data}", "{1'b0, host_data}"),
                           ('missing_clear', "keyboard[7] <= 0", "keyboard[7] <= keyboard[7]")]:
        mutant = WORK / f'{name}.sv'
        text = sources[0].read_text()
        assert text.count(old) == 1
        mutant.write_text(text.replace(old, new), encoding='ascii')
        wsl(['iverilog', '-g2012', '-s', 'tb_keyboard', '-o', linux(executable),
             linux(mutant), linux(sources[1])])
        rejected = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(['vvp', linux(executable)])],
                                  capture_output=True, text=True, timeout=30)
        assert rejected.returncode != 0 and 'keyboard expected=' in rejected.stdout
        controls[name] = rejected.stdout.splitlines()[0]
    result = {'result': output, 'lint': lint or 'Verilator -Wall clean',
              'controls': controls,
              'firmware_windows': {f'{address:04X}': value for address, value in windows.items()},
              'limits': ['isolated candidate; no host/CPU composition',
                         'simultaneous host/clear priority unqualified',
                         'static firmware operand windows; execution not established'],
              'inputs_sha256': {path.relative_to(ROOT).as_posix(): sha(path)
                               for path in [*sources, Path(__file__), firmware, *host_paths, *binaries]}}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print(output)


if __name__ == '__main__':
    main()
