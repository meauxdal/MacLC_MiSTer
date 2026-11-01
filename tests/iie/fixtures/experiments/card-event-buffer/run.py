#!/usr/bin/env python3
"""Check original queued events, ring wraparound and live keyboard drains."""
import os
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-event-live'


def queue_event(world, phase):
    result = event_record(world, phase)
    put = module.timer.BASE.put
    if phase == 4:
        put(result, -0x96c + 31 * 4, 0xff41, 4)
        put(result, -0x8ea, 0)
        put(result, -0x8ec, 0)
    else:
        put(result, -0x96c, 0xff42, 4)
        put(result, -0x8ea, 1)
        put(result, -0x8ec, 1)
    return result


def check_queued(session, phase):
    expected = queue_event(session.event_before[phase], phase)
    index = 31 if phase == 4 else 0
    module.timer.BASE.put(expected, -0x96c + index * 4, 0x8000ff41 if phase == 4 else 0x8000ff42, 4)
    module.timer.BASE.put(expected, -0x8ec, index)
    if os.getenv('IIE_BAD_QUEUE') == '1':
        folder = session.folder
        module.timer.BASE.put(expected, -0x96c + 31 * 4, 0xff41, 4)
        assert (folder / 'queued-4-world.bin').read_bytes() == expected
        assert (folder / 'event-4-trap.bin').read_bytes() == struct.pack('>2I', 0xfff7, 0x2ff720)
        assert (folder / 'event-fault-code.bin').read_bytes() == (folder / 'service4-code.bin').read_bytes()
        assert (folder / 'event-fault-pc.bin').read_bytes() == struct.pack('>2I', 0x20271a, 0x20271e)
        assert len(session.transactions) == 65
        assert not any(write and offset == 24 for write, _, offset, _ in session.transactions)
        raise AssertionError('keyboard queue valid bit missing')
    assert (session.folder / f'queued-{phase}-world.bin').read_bytes() == expected, 'queued world mismatch'


def finish(session):
    inherited_finish(session)
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (session.folder / 'trace.txt').read_text(), re.M)]
    for pc, count in ((0x202480, 4), (0x20249e, 2), (0x20271a, 2), (0x202724, 2), (0x202730, 0), (0x202610, 2), (0x20263c, 2)):
        assert pcs.count(pc) == count, (hex(pc), pcs.count(pc))


def main():
    global module, event_record, inherited_finish
    source = (PARENT / 'run.py').read_text()
    module = type(sys)('buffered_events')
    module.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    once = module.once
    source = source.replace('local/experiments/card-event-live', 'local/experiments/card-event-buffer')
    source = source.replace('IIE_BAD_EVENT', 'IIE_BAD_QUEUE')
    source = source.replace('event keyboard write missing', 'keyboard queue valid bit missing')
    source = source.replace('== 64', '== 65')
    source = once(source, '                timer.BASE.put(world, -0x87a, 0)', '''                timer.BASE.put(world, -0x87a, 1)
                timer.BASE.put(world, -0x8ea, 31)
                timer.BASE.put(world, -0x8ec, 31)
                for index in range(32):
                    timer.BASE.put(world, -0x96c + index * 4, (index + 1) * 0x10000 + 0x1200 + index, 4)''')
    source = once(source,
        '        phase_rows = rows + ([[True, 8, 24, 0x41 if phase == 4 else 0x42]] if phase in (4, 7) else [])',
        '''        phase_rows = rows + ([[False, 8, 9, 0], [False, 8, 9, 0],
            [True, 8, 24, 0x41 if phase == 4 else 0x42], [False, 8, 32, 0x88],
            [True, 8, 32, 0x88], [False, 8, 13, 0xea], [True, 8, 13, 0xea]] if phase in (4, 7) else [])''')
    start = source.index("            if os.getenv('IIE_BAD_QUEUE')")
    end = source.index('            assert fields ==', source.index("raise AssertionError('keyboard queue valid bit missing')", start))
    source = source[:start] + source[end:]
    source = once(source, '            if lane == 10:\n                timer.check_timer',
                  '            if lane == 12:\n                check_queued(session, phase)\n            if lane == 10:\n                timer.check_timer')
    source = once(source, '0x202650, 0x202730, 0x20284a', '0x202650, 0x20271e, 0x20284a')
    source = once(source, 'modeled event source with admitted type-3/type-5 live keyboard writes',
                  'modeled event source with admitted type-3/type-5 keyboard queue wraparound, original drains and modifier/control updates over live PDS')
    source = once(source, 'timer delivery and admitted live event writes', 'admitted queued events and live keyboard drains')
    source = once(source, "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py',",
                  "[ROOT / 'fixtures/experiments/card-event-live/run.py', ROOT / 'fixtures/experiments/card-timer-delivery/run.py',")
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    event_record, inherited_finish = module.event_world, module.scheduler_finish
    module.event_world, module.scheduler_finish, module.check_queued = queue_event, finish, check_queued
    os.environ['IIE_BAD_EVENT'] = '0'
    module.main()


if __name__ == '__main__':
    main()
