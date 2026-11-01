#!/usr/bin/env python3
"""Disable the display mask and reject the resulting renderer bypass."""
import json
import re
import shlex
import subprocess
from pathlib import Path
from prepare import HERE, ROOT, WORK, once, sha
from run import execute, linux


def main():
    pins_path = HERE / 'results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, 'changed service4 input: ' + name
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [WORK / 'tb_cache.sv'] + [Path(name) for name in names[names.index(str(binding)):]]
    sources = [path for path in sources if path.suffix in ('.sv', '.v')]
    broken = WORK / 'mask_off.sv'
    broken.write_text(once(sources[0].read_text(), '        wait(boundary);',
                          '        wait(boundary);\n        transact(1, 0, 33, 0, 0);'), encoding='ascii')
    binary = WORK / 'mask_off.vvp'
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
               '-Ptb_card_platform.FAST=1', '-o', linux(binary), linux(broken), *map(linux, sources[1:])]
    subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], check=True, timeout=30)
    before = set(WORK.glob('code5-*'))
    try:
        execute(5, binary, ROOT / 'local/experiments/card-monitor-resume/initial.hex')
    except AssertionError:
        created = set(WORK.glob('code5-*')) - before
        assert len(created) == 1
        run = created.pop()
        assert 'Renderer boundary not reached' in (run / 'mame.log').read_text(), 'wrong failure'
        pcs = [int(value, 16) - 0x200000 for value in
               re.findall(r'^([0-9A-F]{8}):', (run / 'trace.txt').read_text(), re.M)]
        assert pcs.count(0x1cae) == 2 and 0x1ee0 in pcs and 0xa7e not in pcs
        assert not (run / 'world.bin').exists(), 'renderer boundary unexpectedly reached'
        bus = [json.loads(line) for line in (run / 'bus.jsonl').read_text().splitlines()]
        assert bus[-4:] == [[False, 8, 33, 0]] * 4, bus[-4:]
        assert sum(write and offset == 12 for write, width, offset, value in bus) == 1
        assert sha(run / 'loaded.bin') == sha(ROOT / 'local/experiments/firmware-memory/code/CODE_5.bin')
    else:
        raise AssertionError('mask-off control escaped cache/renderer checks')
    lint = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
            '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
            'maclc_iie_binding', *map(linux, sources[1:])]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(lint)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    inputs = [pins_path, HERE / 'check_controls.py', broken, *sources]
    (HERE / 'control-results.json').write_text(json.dumps({
        'control': 'mask_off', 'rejected': 'original service4 bypasses renderer and attempts a second ACK',
        'run_directory': str(run), 'lint': 'card/binding -Wall passes with inherited exclusions',
        'bus_sha256': sha(run / 'bus.jsonl'), 'trace_sha256': sha(run / 'trace.txt'),
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')
    print('PASS rejected renderer bypass with display mask disabled')


if __name__ == '__main__':
    main()
