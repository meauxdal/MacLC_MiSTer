#!/usr/bin/env python3
"""Check original guest transactions against the Python register candidate."""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from host_model import (ROOT, HostStream, Hypothesis, Trace, conf_prelude,
                        load_conf_resources, rom_probe)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def opaque_zero(offset, width):
    if (offset, width) not in ((8, 8), (4, 16)):
        raise ValueError('unmodeled read')
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', default='measured')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = ROOT / 'local/experiments/host-execution' / args.run
    log = (run / 'mame.log').read_text()
    ram = (run / 'ram.bin').read_bytes()
    metadata = json.loads((run / 'run.json').read_text(encoding='utf-8-sig'))
    assert metadata['source_sha256_before'] == metadata['source_sha256_after']
    assert metadata['mame_exit_code'] == 0
    assert not any(error in log for error in ('LUA ERROR', 'Error in expression',
                                              'Not enough parameters', 'Unknown command'))

    def event(name):
        matches = [line for line in log.splitlines() if line.startswith('DBG ' + name + ' ')]
        assert len(matches) == 1, (name, len(matches))
        return {key: int(value, 16) for key, value in
                re.findall(r'(\w+)=([0-9A-F]+)', matches[0])}

    restored = [line for line in log.splitlines() if line.startswith('DBG EXEC ')]
    assert len(restored) == 3
    assert 'pc=00A4BF08' in restored[0] and 'd1=00000004 d2=00000004' in restored[0]
    assert 'sr=2704 mmu=00 vector8=00A026F0' in restored[0]
    assert 'pc=00A4BCD4' in restored[1] and 'sr=2704' in restored[1]
    assert 'pc=00A4BCEE' in restored[2]
    assert event('SLOT_RETURN')['d0'] == 0
    assert event('DISCOVERY_RETURN')['d0'] == 0xfee00000
    assert event('CONF_CALL')['base'] == 0xfee00000
    assert 'ABSENT_DIALOG' not in log
    assert 'UNMODELED frame=3717 write=false offset=01 width=8' in log
    assert 'BOUNDARY frame=3717 transactions=787657 index=4000 control=00' in log

    expected = Trace()
    model = HostStream(Hypothesis('execution candidate'), opaque_zero, expected)
    assert rom_probe(model)['final_equal']
    probe = expected.summary()
    expected = Trace()
    model.trace = expected
    fork = ROOT / 'local/experiments/startup-runtime/startup/IIe Startup.rsrc'
    assert conf_prelude(model, load_conf_resources(fork))['diagnostic_pending']
    startup = expected.summary()
    assert startup['sha256'] == '3b0a80338b26804c237e9dd7097f4882bb9d6a83ccdc7ca5d1f3c3cf3223a935'

    observed_probe, observed_startup = Trace(), Trace()
    replay = HostStream(Hypothesis('Lua agreement'), opaque_zero)
    with (run / 'bus.jsonl').open() as stream:
        for number, line in enumerate(stream):
            write, width, offset, value = json.loads(line)
            if write:
                replay.write(offset, value, width)
            else:
                assert replay.read(offset, width) == value, number
            (observed_probe if number < 7 else observed_startup).record(write, width, offset, value)
    assert observed_probe.summary() == probe
    assert observed_startup.summary() == startup
    assert replay.index == model.index == 0x4000
    assert replay.control == model.control == 0
    assert replay.memory == model.memory

    root = struct.unpack_from('>I', ram, 0xd24)[0]
    record, records, visited = root, [], set()
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
            records.append(dict(record=record, key=key, type_hi=hi, type_lo=lo,
                                source=source, flags=flags))
        record += 24
    card, = [row for row in records if row['key'] == 0x00ef0000]
    assert (card['type_hi'], card['type_lo'], card['source'], card['flags']) == (
        0x000a0015, 0x00010001, 0xa7f22e, 0)
    paths = [Path(__file__), *[Path(__file__).with_name(name) for name in
             ('execute.lua', 'execute.ps1', 'host_model.py')], fork,
             ROOT / 'fixtures/experiments/startup-discovery/trace.lua',
             ROOT / 'fixtures/experiments/startup-discovery/debug.cmd',
             ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom',
             *sorted((ROOT / 'local/experiments/system-baseline/roms/egret').glob('*.bin')),
             *[run / name for name in ('mame.log', 'bus.jsonl', 'ram.bin',
                                       'instructions.txt', 'run.json')]]
    result = dict(scope='Original LC ROM and installed Startup with synthetic register responses',
                  run=metadata, probe=probe, startup=startup,
                  restored_card=card, slot_return=event('SLOT_RETURN'),
                  discovery_return=event('DISCOVERY_RETURN'), conf_call=event('CONF_CALL'),
                  final_memory_sha256=hashlib.sha256(model.memory).hexdigest(),
                  boundary='First unmodeled byte read at +01; subsequent execution excluded',
                  tools={name: sha(Path('C:/Users/Elle/Downloads/mame0289b_x64') / name)
                         for name in ('mame.exe', 'chdman.exe')},
                  artifacts={path.relative_to(ROOT).as_posix(): sha(path) for path in paths})
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS: original ROM restoration, Startup discovery, exact probe/prelude and model agreement')


if __name__ == '__main__':
    main()
