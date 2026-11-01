#!/usr/bin/env python3
"""Check card CPU strobe consumption followed by original host queue drains."""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-event-live'


def recovery_world(world, phase):
    result = event_record(world, phase)
    put = module.timer.BASE.put
    if phase == 4:
        put(result, -0x96c + 31 * 4, 0x8000ff41, 4)
        put(result, -0x8ea, 0)
    else:
        put(result, -0x96c + 31 * 4, 0xff41, 4)
        put(result, -0x96c, 0xff42, 4)
        put(result, -0x8ea, 1)
        put(result, -0x8ec, 1)
    return result


def check_queued(session, phase):
    expected = recovery_world(session.event_before[phase], phase)
    if phase == 7:
        module.timer.BASE.put(expected, -0x96c, 0x8000ff42, 4)
        module.timer.BASE.put(expected, -0x8ec, 0)
    assert (session.folder / f'queued-{phase}-world.bin').read_bytes() == expected


def check_reply(session, phase, lane, sequence, response):
    if CONTROL and phase == 7 and lane == 11:
        assert list(map(int, response[1:])) == [104, 0x80], response
        assert len(session.transactions) == 103
        session.transactions.append([False, 8, 9, 0x80])
        assert 'CONSUME before=d5 after=d5 reads=2 clears=1 ignore=1' in session.output
        assert not any(write and offset == 24 for write, _, offset, _ in session.transactions)
        raise AssertionError('keyboard strobe clear missing')


def finish(session):
    assert session.receive('RECOVERY') == 'RECOVERY keyboard=42 pulses=3'
    inherited_finish(session)
    assert 'CONSUME before=d5 after=55 reads=2 clears=1 ignore=0' in session.output
    tail = (session.folder / 'instructions.txt').read_text().splitlines()[-6:]
    assert [line.split()[:2] for line in tail] == [
        ['fb65', 'ad'], ['fb68', '8d'], ['fb6b', '2c'],
        ['fb6e', 'ad'], ['fb71', '8d'], ['fb74', '4c']], tail


def main():
    global module, event_record, inherited_finish, CONTROL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    CONTROL = args.control
    os.environ['IIE_BAD_CONSUME'] = str(int(CONTROL))
    os.environ['IIE_FULL_QUEUE'] = '0'
    os.environ['IIE_BAD_BUSY'] = '0'
    sys.path.insert(0, str(HERE.parent / 'card-reload-callback'))
    import live
    live_source = live.__file__
    source = Path(live_source).read_text().replace("'+sys_phase=2'", "'+sys_phase=2', '+ignore_key_clear=' + os.environ['IIE_BAD_CONSUME']")
    exec(compile('import os\n' + source, live_source, 'exec'), live.__dict__)
    source = (PARENT / 'run.py').read_text()
    module = type(sys)('keyboard_recovery')
    module.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    once = module.once
    source = source.replace('local/experiments/card-event-live', 'local/experiments/card-keyboard-recovery')
    source = source.replace('IIE_BAD_EVENT', 'IIE_BAD_CONSUME')
    source = source.replace('event keyboard write missing', 'keyboard strobe clear missing')
    source = source.replace('== 64', '== 104')
    source = once(source, '                timer.BASE.put(world, -0x87a, 0)', '''                timer.BASE.put(world, -0x87a, 1)
                timer.BASE.put(world, -0x8ea, 31)
                timer.BASE.put(world, -0x8ec, 31)
                for index in range(32):
                    timer.BASE.put(world, -0x96c + index * 4, (index + 1) * 0x10000 + 0x1200 + index, 4)''')
    source = once(source,
        '        phase_rows = rows + ([[True, 8, 24, 0x41 if phase == 4 else 0x42]] if phase in (4, 7) else [])',
        '''        phase_rows = rows + ([[False, 8, 9, 0x80], [False, 8, 9, 0x80],
            [False, 8, 32, 0x88], [True, 8, 32, 0x88], [False, 8, 13, 0xea], [True, 8, 13, 0xea]] if phase == 4 else
            [[False, 8, 9, 0], [True, 8, 24, 0x41], [False, 8, 9, 0], [True, 8, 24, 0x42],
             [False, 8, 32, 0x88], [True, 8, 32, 0x88], [False, 8, 13, 0xea], [True, 8, 13, 0xea]] if phase == 7 else [])''')
    start = source.index("            if os.getenv('IIE_BAD_CONSUME')")
    end = source.index('            assert fields ==', source.index("raise AssertionError('keyboard strobe clear missing')", start))
    source = source[:start] + source[end:]
    source = once(source, '            assert list(map(int, response[1:])) == [sequence, row[3]], response',
                  '            check_reply(session, phase, lane, sequence, response)\n            assert list(map(int, response[1:])) == [sequence, row[3]], response')
    source = once(source, '            if lane == 10:\n                timer.check_timer',
                  '            if (phase == 4 and lane == 12) or (phase == 7 and lane == 13):\n                check_queued(session, phase)\n            if lane == 10:\n                timer.check_timer')
    source = once(source, '0x202650, 0x202730, 0x20284a', '0x202650, 0x20271e, 0x20284a')
    source = once(source, 'modeled event source with admitted type-3/type-5 live keyboard writes',
                  'modeled event source, synthetic card CPU consumer at patched monitor tail and original host queue drains after busy-to-ready transition')
    source = once(source, 'timer delivery and admitted live event writes', 'CPU strobe consumption and host queue recovery')
    source = once(source, 'missing event keyboard write rejected', 'missing CPU strobe clear rejected')
    source = once(source, "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py',",
                  "[ROOT / 'fixtures/experiments/card-event-live/run.py', ROOT / 'fixtures/experiments/card-timer-delivery/run.py',")
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    event_record, inherited_finish = module.event_world, module.scheduler_finish
    module.event_world, module.scheduler_finish = recovery_world, finish
    module.check_reply, module.check_queued = check_reply, check_queued
    module.main()
    path = HERE / f'{"control" if CONTROL else "results"}-{args.driver}-48.json'
    record = json.loads(path.read_text())
    run = record['runs'][0]
    run.update(vbl_callbacks=7, timer_callbacks_started=7, timer_callbacks_completed=7,
               admitted_callbacks=[4, 7], event_types=[3, 5], seeded_keyboard=0xd5,
               consumer='synthetic LDA/STA/BIT/LDA/STA/JMP at FB65',
               event_writes_forwarded=sum(write and offset == 24 for write, _, offset, _ in run['transactions']))
    path.write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
