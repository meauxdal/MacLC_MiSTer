#!/usr/bin/env python3
"""Validate the bounded, cardless Startup discovery capture."""

import argparse
import hashlib
import importlib.util
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE_HASH = '5e6b04f58dcf631748baf655d0f5d398d6ecb6729f42226f00dfd378c15f2e60'
FORK_HASH = '5674f658f77e333a91c309f477e2cfbc703c781cc5f914545974fe44d2ecce8c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fields(line):
    return {key: int(value, 10 if key == 'frame' else 16) for key, value in
            re.findall(r'(\w+)=([0-9A-F]+)\b', line)}


def parameter_block(raw):
    blob = bytes.fromhex(raw)
    assert len(blob) == 56
    result = {'hex': raw.lower()}
    for name, offset, fmt in (
        ('spsPointer', 4, 'I'), ('spParamData', 24, 'I'),
        ('spCategory', 40, 'H'), ('spCType', 42, 'H'),
        ('spDrvrSW', 44, 'H'), ('spDrvrHW', 46, 'H'),
        ('spTBMask', 48, 'B'), ('spSlot', 49, 'B'),
        ('spID', 50, 'B'), ('spExtDev', 51, 'B'),
    ):
        result[name] = struct.unpack_from('>' + fmt, blob, offset)[0]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='verified')
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).with_name('RESULTS.json'))
    args = parser.parse_args()
    run = ROOT / 'local/experiments/startup-discovery' / args.run
    log = (run / 'mame.log').read_text(encoding='utf-8')
    trace = (run / 'instructions.txt').read_text(encoding='utf-8')
    metadata = json.loads((run / 'run.json').read_text(encoding='ascii'))
    assert metadata['source_sha256_before'] == metadata['source_sha256_after'] == SOURCE_HASH
    assert metadata['mame_exit_code'] == 0
    assert sha(ROOT / 'local/hardfiles/Apple-II_100MB.hda') == SOURCE_HASH
    assert not any(error in log for error in ('LUA ERROR', 'Error in expression',
                                              'Not enough parameters', 'Unknown command'))

    def event(name):
        lines = [line for line in log.splitlines() if line.startswith('DBG ' + name + ' ')]
        assert len(lines) == 1, (name, len(lines))
        return fields(lines[0])

    enter = event('SLOT_ENTER')
    returned = event('SLOT_RETURN')
    discovery = event('DISCOVERY_RETURN')
    absent = event('ABSENT_DIALOG')
    pre = parameter_block(re.search(r'DBG PRE pb=([0-9A-F]+)', log)[1])
    post = parameter_block(re.search(r'DBG POST pb=([0-9A-F]+)', log)[1])
    assert enter['pc'] == 0xa06e16 and enter['d0'] == 0x15
    assert enter['mach'] == 0x13 and enter['processor'] == 3
    assert enter['a0'] == enter['a6'] - 0x42
    assert [pre[key] for key in ('spCategory', 'spCType', 'spDrvrSW', 'spDrvrHW',
                                'spTBMask', 'spSlot', 'spID', 'spExtDev')] == [10, 21, 1, 0, 1, 0, 0, 0]
    base = enter['code2']
    assert returned['pc'] == base + 0x99a and returned['d0'] & 0xffff == 0xfea8
    assert returned['a0'] == enter['a0']
    assert discovery['pc'] == base + 0x780 and discovery['d0'] == 0
    assert absent['pc'] == base + 0x790 and absent['message'] == 5 and absent['base'] == 0
    assert 'CONF_CALL' not in log and 'CANDIDATE_ACCESS' not in log
    assert log.count('WATCH id=') == 4
    assert 'FINAL CurApName="IIe Startup"' in log

    spec = importlib.util.spec_from_file_location(
        'resources', ROOT / 'fixtures/research/software-bringup/inspect_resources.py')
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    fork = ROOT / 'local/experiments/startup-runtime/startup/IIe Startup.rsrc'
    assert sha(fork) == FORK_HASH
    code = next(raw for meta, raw in inspector.resources(fork.read_bytes())
                if meta['type'] == 'CODE' and meta['id'] == 2)
    ram = (run / 'ram.bin').read_bytes()
    assert ram[base:base + len(code)] == code
    assert struct.unpack_from('>I', ram, enter['a5'] - 0x11e2)[0] == 0
    for offset in (0x99a, 0x99c, 0x9b6, 0x9b8, 0x9c8, 0x9ca,
                   0x780, 0x784, 0x786, 0x788, 0x78a, 0x78c, 0x78e, 0x790):
        assert re.search(rf'^{base + offset:08X}:', trace, re.MULTILINE), hex(offset)
    assert '00A066FC: move.w  #$fea8, D0' in trace
    candidates = [fields(line) for line in log.splitlines()
                  if line.startswith('DBG SRT_CANDIDATE ')]
    assert len(candidates) == 3
    for candidate in candidates:
        offset = candidate['record']
        assert struct.unpack_from('>I', ram, offset)[0] == candidate['key']
        assert struct.unpack_from('>II', ram, offset + 8) == (
            candidate['type_hi'], candidate['type_lo'])
        assert (candidate['type_hi'], candidate['type_lo'] & 0xffff0000) != (0x000a0015, 0x00010000)

    paths = [ROOT / 'local/hardfiles/Apple-II_100MB.hda', fork,
             ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom',
             *sorted((ROOT / 'local/experiments/system-baseline/roms/egret').glob('*.bin')),
             run / 'mame.log', run / 'instructions.txt', run / 'ram.bin',
             run / 'capture/discovery.png', run / 'run.json',
             *[Path(__file__).with_name(name) for name in
               ('trace.lua', 'run.ps1', 'debug.cmd', 'analyze.py')]]
    artifacts = [{'path': path.relative_to(ROOT).as_posix(),
                  'bytes': path.stat().st_size, 'sha256': sha(path)} for path in paths]
    tool = Path('C:/Users/Elle/Downloads/mame0289b_x64/mame.exe')
    result = {'date': '2026-10-22', 'engine': 'MAME 0.289', 'machine': 'maclc',
              'repository_head': '0cc0600ae13700b68d2935da888cc4a74e38b267',
              'startup': '2.2.2d1', 'ram': '4M', 'pds': 'empty',
              'run': metadata, 'slot_enter': enter, 'slot_return': returned,
              'result_signed_word': -344, 'error': 'smNoMoresRsrcs',
              'pb_before': pre, 'pb_after': post, 'srt_candidates': candidates,
              'discovery_return': discovery, 'absent_dialog': absent,
              'live_code2_bytes_identical': len(code),
              'conf_call_hits': 0, 'candidate_window_hits': 0,
              'trace_instruction_lines': len(re.findall(r'^[0-9A-F]{8}:', trace, re.MULTILINE)),
              'mame_sha256': sha(tool), 'artifacts': artifacts}
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS: original CODE 2, Slot Manager failure, zero base, absent dialog, four watched windows')


if __name__ == '__main__':
    main()
