#!/usr/bin/env python3
"""Reject fixed-Cx routing and corrupted original slot-3 contents."""
import json
import shlex
import subprocess
from prepare import HERE, ROOT, WORK, once, prepare, sha
from run import linux, wsl


def main():
    pins_path = HERE / 'results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(ROOT / name) == digest, 'changed resume input: ' + name
    closure, _ = prepare()
    bench = WORK / 'tb_monitor.sv'
    sources = [bench, ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv',
               *closure, ROOT / 'local/experiments/maclc-iie-build/sdram.v']
    card = WORK / 'card_irq_candidate.sv'
    image = WORK / 'initial.hex'
    fixed = WORK / 'fixed_cx.sv'
    fixed.write_text(once(card.read_text(), 'parameter FIXED_CX = 0', 'parameter FIXED_CX = 1'), encoding='ascii')
    broken_image = WORK / 'bad_slot3.hex'
    values = image.read_text().splitlines()
    assert values[0x2C307] == 'ea'
    values[0x2C307] = '18'
    broken_image.write_text('\n'.join(values) + '\n', encoding='ascii')
    controls = []
    for name, variant, initial, expected in (
        ('fixed_cx', [fixed if path == card else path for path in sources], image, 'monitor unselected Cx read'),
        ('bad_slot3', sources, broken_image, 'monitor external slot3 probe mismatch'),
    ):
        binary = WORK / f'{name}.vvp'
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
             '-Ptb_card_platform.FAST=1', '-o', linux(binary), *map(linux, variant)])
        result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join([
            'vvp', linux(binary), '+image=' + linux(initial), '+trace=' + linux(WORK / f'{name}-captures.txt'),
            '+instructions=' + linux(WORK / f'{name}-instructions.txt')])],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and expected in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'control': name, 'result': result.stdout.strip()})
        print('PASS rejected ' + name, flush=True)
    inputs = sources + [image, fixed, broken_image, pins_path, HERE / 'check_controls.py']
    (HERE / 'control-results.json').write_text(json.dumps({
        'controls': controls, 'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
