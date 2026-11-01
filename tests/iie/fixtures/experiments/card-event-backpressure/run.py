#!/usr/bin/env python3
"""Check busy-keyboard retention and full-queue rejection in both drivers."""
import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-event-live'


def queued_world(world, phase):
    result = event_record(world, phase)
    if not FULL:
        put = module.timer.BASE.put
        put(result, -0x96c + (31 if phase == 4 else 0) * 4, 0x8000ff41 if phase == 4 else 0x8000ff42, 4)
        put(result, -0x8ea, 0 if phase == 4 else 1)
    return result


def check_protocol(session, phase, lane, fields):
    if lane == 12:
        expected = queued_world(session.event_before[phase], phase)
        if CONTROL and FULL:
            module.timer.BASE.put(expected, -0x96c + 31 * 4, 0x8000ff41, 4)
            module.timer.BASE.put(expected, -0x8ea, 0)
        assert (session.folder / f'queued-{phase}-world.bin').read_bytes() == expected, 'busy queued world mismatch'
        if CONTROL and FULL:
            assert fields == [66, 0, 8, 9, 0], fields
            check_fault(session, 0x202718, 0x20271a, event_record(session.event_before[phase], phase))
            assert len(session.transactions) == 65
            raise AssertionError('keyboard backpressure guard missing')
    if CONTROL and not FULL and phase == 4 and lane == 13:
        assert fields == [67, 1, 8, 24, 0x41], fields
        check_fault(session, 0x202486, 0x202488, queued_world(session.event_before[phase], phase))
        assert len(session.transactions) == 66
        raise AssertionError('keyboard backpressure guard missing')


def check_fault(session, start, end, world):
    folder = session.folder
    assert (folder / 'busy-fault-pc.bin').read_bytes() == struct.pack('>2I', start, end)
    assert (folder / 'busy-fault-code.bin').read_bytes() == (folder / 'service4-code.bin').read_bytes()
    assert (folder / 'busy-fault-world.bin').read_bytes() == world
    assert not any(write and offset == 24 for write, _, offset, _ in session.transactions)


def finish(session):
    assert session.receive('BUSY') == 'BUSY keyboard=d5 pulses=1'
    inherited_finish(session)
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (session.folder / 'trace.txt').read_text(), re.M)]
    for pc, count in ((0x202480, 4), (0x202488, 0), (0x202496, 0),
                      (0x20271a, 0 if FULL else 2), (0x202724, 0 if FULL else 2), (0x202610, 2)):
        assert pcs.count(pc) == count, (hex(pc), pcs.count(pc))
    assert 'BUSY keyboard=d5 pulses=1' in session.output


def main():
    global module, event_record, inherited_finish, FULL, CONTROL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    FULL, CONTROL = args.full, args.control
    if FULL:
        sys.argv.remove('--full')
    os.environ['IIE_FULL_QUEUE'] = str(int(FULL))
    source = (PARENT / 'run.py').read_text()
    module = type(sys)('busy_events')
    module.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    once = module.once
    source = source.replace('local/experiments/card-event-live', 'local/experiments/card-event-backpressure')
    source = source.replace('IIE_BAD_EVENT', 'IIE_BAD_BUSY')
    source = source.replace('event keyboard write missing', 'keyboard backpressure guard missing')
    source = source.replace('== 64', '== ' + ('65' if FULL else '66'))
    source = once(source, '                timer.BASE.put(world, -0x87a, 0)', '''                timer.BASE.put(world, -0x87a, 1)
                timer.BASE.put(world, -0x8ea, 31)
                timer.BASE.put(world, -0x8ec, 31)
                for index in range(32):
                    timer.BASE.put(world, -0x96c + index * 4, (0x80000000 if FULL else 0) + (index + 1) * 0x10000 + 0x1200 + index, 4)''')
    source = once(source,
        '        phase_rows = rows + ([[True, 8, 24, 0x41 if phase == 4 else 0x42]] if phase in (4, 7) else [])',
        '''        phase_rows = rows + ([[False, 8, 9, 0x80], [False, 8, 9, 0x80],
            [False, 8, 32, 0x88], [True, 8, 32, 0x88],
            [False, 8, 13, 0xea], [True, 8, 13, 0xea]] if phase in (4, 7) else [])''')
    start = source.index("            if os.getenv('IIE_BAD_BUSY')")
    end = source.index('            assert fields ==', source.index("raise AssertionError('keyboard backpressure guard missing')", start))
    source = source[:start] + source[end:]
    source = once(source, '            assert fields == [sequence, int(row[0]),',
                  '            if lane in (12, 13):\n                check_protocol(session, phase, lane, fields)\n            assert fields == [sequence, int(row[0]),')
    source = once(source, '0x202650, 0x202730, 0x20284a',
                  '0x202650, ' + ('0x202718' if FULL else '0x20271e') + ', 0x20284a')
    source = once(source, "        'EVENT write=1 keyboard=41', 'EVENT write=2 keyboard=42']", '        ]')
    source = once(source, 'modeled event source with admitted type-3/type-5 live keyboard writes',
                  'modeled event source, seeded busy keyboard and ' + ('full-queue rejection' if FULL else 'queued-event retention') + ' over live PDS')
    source = once(source, 'timer delivery and admitted live event writes', 'busy keyboard and queue backpressure')
    source = once(source, 'missing event keyboard write rejected', 'missing keyboard backpressure guard rejected')
    source = once(source, "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py',",
                  "[ROOT / 'fixtures/experiments/card-event-live/run.py', ROOT / 'fixtures/experiments/card-timer-delivery/run.py',")
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    event_record, inherited_finish = module.event_world, module.scheduler_finish
    module.event_world, module.scheduler_finish, module.check_protocol, module.FULL = queued_world, finish, check_protocol, FULL
    module.main()
    path = HERE / f'{"control" if CONTROL else "results"}-{args.driver}-48.json'
    record = json.loads(path.read_text())
    run = record['runs'][0]
    run['queue_profile'] = 'full' if FULL else 'retained'
    run['seeded_keyboard'] = 0xd5
    run['event_writes_forwarded'] = sum(write and offset == 24 for write, _, offset, _ in run['transactions'])
    target = path.with_name(path.stem + ('-full' if FULL else '-retained') + path.suffix)
    target.write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    path.unlink()


if __name__ == '__main__':
    main()
