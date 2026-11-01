#!/usr/bin/env python3
"""Validate ROM identity, table lifecycle and the cardless boot probe."""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from probe_model import evaluate


ROOT = Path(__file__).resolve().parents[3]
SOURCE_HASH = '5e6b04f58dcf631748baf655d0f5d398d6ecb6729f42226f00dfd378c15f2e60'
ROM_HASH = '129391cc72f84c2b321709cad8281e30a45e50b3cf6e7afe7434c4d32c7b9d5b'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fields(line):
    return {key: int(value, 10 if key in ('frame', 'size') else 16)
            for key, value in re.findall(r'(\w+)=([0-9A-F]+)\b', line)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='verified-final')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('RESULTS.json'))
    args = parser.parse_args()
    run = ROOT / 'local/experiments/slot-identity' / args.run
    log = (run / 'mame.log').read_text(encoding='utf-8')
    build_trace = (run / 'build.txt').read_text(encoding='utf-8')
    primary_trace = (run / 'primary.txt').read_text(encoding='utf-8')
    ram = (run / 'ram.bin').read_bytes()
    rom_path = ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom'
    rom = rom_path.read_bytes()
    metadata = json.loads((run / 'run.json').read_text(encoding='ascii'))
    assert metadata['source_sha256_before'] == metadata['source_sha256_after'] == SOURCE_HASH
    assert sha(ROOT / 'local/hardfiles/Apple-II_100MB.hda') == SOURCE_HASH
    assert sha(rom_path) == ROM_HASH and metadata['mame_exit_code'] == 0
    assert not any(error in log for error in ('LUA ERROR', 'Error in expression',
                                              'Not enough parameters', 'Unknown command'))

    def events(name):
        return [fields(line) for line in log.splitlines() if line.startswith('DBG ' + name + ' ')]

    def pointer(offset, resource_id):
        assert rom[offset] == resource_id
        return offset + int.from_bytes(rom[offset + 1:offset + 4], 'big', signed=True)

    card = pointer(0x7ec8a, 0xef)
    kind = pointer(card, 1)
    name = pointer(card + 4, 2)
    assert card == 0x7f22e and kind == 0x7f24e and name == 0x7f28a
    type_tuple = struct.unpack_from('>4H', rom, kind)
    assert type_tuple == (10, 21, 1, 1)
    assert rom[name:rom.index(b'\0', name)].decode('ascii') == 'CPU_AppleII_AppleIIe_FeatureCard'
    assert pointer(pointer(0x7ec1a, 1) + 12, 0x22) == 0x7edec
    assert rom[0x4b970:0x4b974] == b'DAF!'

    built = events('SRT_BUILD')
    built_card = [event for event in built if event['key'] == 0x00ef0000]
    removed = [event for event in events('SRT_DELETE') if event['key'] == 0x00ef0000]
    assert len(built) == 30 and len(built_card) == len(removed) == 1
    assert built_card[0]['type_hi'] == removed[0]['type_hi'] == 0x000a0015
    assert built_card[0]['type_lo'] == removed[0]['type_lo'] == 0x00010001
    assert built_card[0]['source'] == 0xa00000 + card and built_card[0]['flags'] == 0
    assert built_card[0]['frame'] < removed[0]['frame']
    probes = {event['pc']: event for event in events('PROBE')}
    assert 0xa4bcee not in probes and 0xa4bf0e not in probes
    assert probes[0xa4b9ea]['d0'] == 0
    assert probes[0xa4bca2]['d0'] & 0xffff == 0xfea8
    assert probes[0xa4bcce]['d0'] & 0xffff == 0xfea8
    entry, active, restored = (probes[site] for site in (0xa4beb0, 0xa4beda, 0xa4bf08))
    assert (entry['mmu'], active['mmu'], restored['mmu']) == (0, 1, 0)
    assert active['a3'] == 0xfe000000 and active['vector8'] == 0xa4bf0e
    assert restored['vector8'] == entry['vector8']
    assert restored['d1'] == 4 and restored['d2'] == 0 and restored['sr'] & 4 == 0
    assert probes[0xa4bcd4]['sr'] & 4 == 0
    bus = events('PROBE_BUS')
    assert [(event['address'], event['size'], event['data']) for event in bus] == [
        (0x8000001c, 16, 0), (0x80000010, 16, 0), (0x8000001c, 16, 0)]
    for site in (0xa4b9e0, 0xa4b9e8, 0xa4bcd0, 0xa4beda, 0xa4bede,
                 0xa4bee4, 0xa4bee8, 0xa4befa, 0xa4bf06, 0xa4bcd4):
        assert re.search(rf'^{site:08X}:', primary_trace, re.MULTILINE)
    assert '00A4BEEA:' not in primary_trace and '00A4BCEE:' not in primary_trace
    assert '00A0617E:' in build_trace

    root = struct.unpack_from('>I', ram, 0xd24)[0]
    record, final_records, visited = root, [], set()
    while True:
        assert record not in visited and 0 <= record <= len(ram) - 24
        visited.add(record)
        marker = struct.unpack_from('>H', ram, record)[0]
        if marker == 0xffff:
            link = struct.unpack_from('>I', ram, record + 2)[0]
            if not link:
                break
            record = link
            continue
        if marker < 0x8000:
            key, _, hi, lo, source, flags = struct.unpack_from('>6I', ram, record)
            final_records.append({'record': record, 'key': key, 'type_hi': hi,
                                  'type_lo': lo, 'source': source, 'flags': flags})
        record += 24
    assert len(final_records) == 3
    assert all(row['type_hi'] != 0x000a0015 for row in final_records)
    paths = [rom_path, ROOT / 'local/hardfiles/Apple-II_100MB.hda',
             *sorted((ROOT / 'local/experiments/system-baseline/roms/egret').glob('*.bin')),
             *[run / name for name in ('run.json', 'mame.log', 'build.txt', 'primary.txt', 'ram.bin')],
             *[Path(__file__).with_name(name) for name in
               ('trace.lua', 'run.ps1', 'debug.cmd', 'probe_model.py', 'analyze.py')]]
    tools = Path('C:/Users/Elle/Downloads/mame0289b_x64')
    result = {'date': '2026-10-22', 'engine': 'MAME 0.289', 'machine': 'maclc',
              'ram': '4M', 'pds': 'empty', 'run': metadata,
              'rom_card_directory': 0xa00000 + card, 'rom_type_address': 0xa00000 + kind,
              'rom_name_address': 0xa00000 + name, 'rom_type_tuple': type_tuple,
              'rom_name': 'CPU_AppleII_AppleIIe_FeatureCard',
              'probe_helper_address': 0xa4beb0,
              'probe_helper_bytes': 0x4bf54 - 0x4beb0,
              'probe_helper_sha256': hashlib.sha256(rom[0x4beb0:0x4bf54]).hexdigest(),
              'built_records': len(built), 'built_card': built_card[0], 'deleted_card': removed[0],
              'probe_events': events('PROBE'), 'bus_events': bus,
              'final_root': root, 'final_records': final_records, 'probe_model': evaluate(),
              'tool_hashes': {name: sha(tools / name) for name in ('mame.exe', 'unidasm.exe', 'chdman.exe')},
              'artifacts': [{'path': path.relative_to(ROOT).as_posix(),
                             'bytes': path.stat().st_size, 'sha256': sha(path)} for path in paths]}
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS: ROM identity, build/delete lifecycle, failed physical-address probe, restored mode/vector')
    print('Model: one-step passes 65536 indices; zero/two-step each falsely accept only $FFFC')


if __name__ == '__main__':
    main()
