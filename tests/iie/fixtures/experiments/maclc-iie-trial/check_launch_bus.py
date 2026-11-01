#!/usr/bin/env python3
"""Exercise the hardware trial's first launch accesses with the actual host CPU."""
import hashlib
import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/maclc-iie-trial'
MACLC = ROOT.parent / 'MacLC_MiSTer'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    kind = 'control' if args.control else 'results'
    pins = json.loads((HERE / 'project-results.json').read_text())['generated_sha256']
    closure = [Path(name) for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"',
                                               (WORK / 'card_platform.qip').read_text())]
    for path in closure:
        assert sha(path) == pins[str(path)], str(path)
    candidate = next(path for path in closure if path.name == 'card_irq_candidate.sv')
    old = '(!capture_valid || !capture_write);'
    new = '(cpu_running && !capture_valid);'
    source = candidate.read_text()
    assert source.count(old) + source.count(new) == 1
    source = source.replace(new, old) if args.control else source.replace(old, new)
    patched = WORK / f'launch-rmw-card-{kind}.sv'
    patched.write_text(source, encoding='ascii')
    closure = [patched if path == candidate else path for path in closure]
    host = [MACLC / 'rtl/tg68k' / name for name in
            ('TG68K_Pack.sv', 'TG68K_ALU.v', 'TG68KdotC_Kernel.v', 'tg68k.v')]
    conf_path = ROOT / 'local/experiments/firmware-memory/code/Conf_1000.bin'
    inventory = ROOT / 'local/experiments/firmware-memory/resources.json'
    resource = next(item for item in json.loads(inventory.read_text())['resources']
                    if item['type'] == 'Conf' and item['id'] == 1000)
    assert sha(conf_path) == resource['sha256']
    program = bytes.fromhex('287cfe000000') + conf_path.read_bytes()[0xa:0x1c] + bytes.fromhex('13fc005a0000020060fe')
    rom = bytearray(bytes.fromhex('4e71') * 256)
    rom[:8] = bytes.fromhex('0001000000000100')
    rom[0x100:0x100 + len(program)] = program
    image = WORK / 'launch-program.hex'
    image.write_text(''.join(f'{int.from_bytes(rom[i:i+2], "big"):04x}\n' for i in range(0, len(rom), 2)), encoding='ascii')
    sources = [HERE / 'tb_launch_bus.sv', *closure, *host]
    binary = WORK / f'launch-bus-{kind}.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb_launch_bus', '-o', linux(binary), *map(linux, sources)]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(['wsl', '--exec', 'vvp', linux(binary), '+program=' + linux(image)], capture_output=True, text=True, timeout=60)
    (WORK / f'launch-bus-{kind}.log').write_text(result.stdout + result.stderr, encoding='ascii')
    print(result.stdout, end='')
    if args.control:
        assert result.returncode != 0 and 'address=fe00000c' in result.stdout and 'fault=0 error=1' in result.stdout
        assert result.stdout.count('PDS address=') == 4
    else:
        assert result.returncode == 0, result.stderr
    record = {'scope': 'Actual TG68K and exact trial card frontend; synthetic launch prefix and host ROM',
              'output': result.stdout.splitlines(), 'inputs_sha256': {str(path): sha(path) for path in
                  [*sources, conf_path, inventory, image, Path(__file__)]}}
    record['control'] = args.control
    (HERE / ('launch-bus-control.json' if args.control else 'launch-bus-results.json')).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
