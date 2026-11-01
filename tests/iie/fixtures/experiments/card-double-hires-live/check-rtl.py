#!/usr/bin/env python3
"""Check the RTL component using precomputed host transactions, without MAME."""
import argparse
import json
import shlex
import subprocess
import run as bridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--mixed', action='store_true')
    parser.add_argument('--page2', action='store_true')
    args = parser.parse_args()
    mode = 0x28 | (4 if args.mixed else 0) | (2 if args.page2 else 0)
    sources, image, inputs = bridge.prepare()
    data = bridge.double.raw_images()
    (bridge.WORK / 'hires.hex').write_text(''.join(f'{v:02x}\n' for v in data[0]), encoding='ascii')
    (bridge.WORK / 'aux.hex').write_text(''.join(f'{v:02x}\n' for v in data[1]), encoding='ascii')
    seed = 252 if args.driver == 5 else 255
    expected, first = bridge.expected_transactions(seed, mode, data)
    stem = f'rtl-check-{args.driver}-{mode:02x}'
    binary = bridge.WORK / (stem + '.vvp')
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
        '-Ptb_card_platform.FAST=1', '-Ptb_card_platform.BAD_PAUSE=0',
        f'-Ptb_card_platform.FIRST_ACK={first}', f'-Ptb_card_platform.LAST_ACK={len(expected)}',
        f'-Ptb_card_platform.HIRES_MASK={bridge.display_mask(mode)}', '-o', bridge.linux(binary), *map(bridge.linux, sources)]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    capture = bridge.WORK / (stem + '-captures.txt')
    instructions = bridge.WORK / (stem + '-instructions.txt')
    stimulus = ''.join(f'{i} {int(write)} {width} {offset} {value if write else 0}\n'
        for i, (write, width, offset, value) in enumerate(expected, 1))
    command = ['wsl', '--exec', 'vvp', bridge.linux(binary), '+image=' + bridge.linux(image),
        '+trace=' + bridge.linux(capture), '+instructions=' + bridge.linux(instructions), '+sys_phase=2', f'+mask={seed}']
    result = subprocess.run(command, input=stimulus, capture_output=True, text=True, timeout=20)
    output = result.stdout + result.stderr
    log = bridge.WORK / (stem + '.log')
    log.write_text(output, encoding='ascii')
    assert result.returncode == 0, output[-2500:]
    replies = [list(map(int, line.split()[1:])) for line in output.splitlines() if line.startswith('REPLY ')]
    assert replies == [[i, row[3]] for i, row in enumerate(expected, 1)]
    assert 'PASS page2 rendered' in output
    inputs += [bridge.HERE / 'run.py', bridge.HERE / 'check-rtl.py', bridge.DOUBLE / 'run.py', *sources, bridge.WORK / 'hires.hex', bridge.WORK / 'aux.hex']
    record = {'scope': 'RTL with precomputed host transactions; no concurrent host pixel checks or ACK gating',
        'driver': args.driver, 'mode': mode, 'transactions_checked': len(expected),
        'rtl_result': [line for line in output.splitlines() if not line.startswith('REPLY ')],
        'hashes': {str(path): bridge.sha(path) for path in (log, capture, instructions)},
        'inputs_sha256': {str(path): bridge.sha(path) for path in inputs}}
    (bridge.HERE / (stem + '.json')).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'RTL ONLY PASS CODE {args.driver} mode {mode:02x}: READY, all replies, both RTIs, main clear and auxiliary fixture')


if __name__ == '__main__':
    main()
