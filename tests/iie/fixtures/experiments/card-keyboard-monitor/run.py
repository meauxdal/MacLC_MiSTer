#!/usr/bin/env python3
"""Check original monitor keyboard consumption and live host queue drains."""
import argparse
import json
import os
import shutil
import struct
import sys
import time
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
        if DEFERRED:
            put(result, -0x96c, 0x8000ff42, 4)
            put(result, -0x8ec, 0)
    return result


def check_queued(session, phase):
    expected = recovery_world(session.event_before[phase], phase)
    if phase == 7:
        module.timer.BASE.put(expected, -0x96c, 0x8000ff42, 4)
        module.timer.BASE.put(expected, -0x8ec, 0)
    assert (session.folder / f'queued-{phase}-world.bin').read_bytes() == expected


def check_reply(session, phase, lane, sequence, response):
    if CONTROL and not DEFERRED and phase == 7 and lane == 13:
        assert list(map(int, response[1:])) == [106, 0x80], response
        assert len(session.transactions) == 105
        session.transactions.append([False, 8, 9, 0x80])
        assert 'CONSUME before=c1 after=c1 reads=2 clears=1 ignore=1' in session.output
        assert sum(write and offset == 24 for write, _, offset, _ in session.transactions) == 1
        raise AssertionError('keyboard strobe clear missing')


def exchange_deferred(session, host):
    for sequence, row in ((111, [False, 8, 9, 0]), (112, [True, 8, 24, 0x42])):
        path = session.folder / f'request-{sequence}.txt'
        deadline = time.monotonic() + 20
        while not path.exists():
            assert host.poll() is None and time.monotonic() < deadline, 'Missing deferred request'
            time.sleep(0.002)
        fields = list(map(int, path.read_text().split()))
        assert fields == [sequence, int(row[0]), row[1], row[2], row[3] if row[0] else 0], fields
        session.process.stdin.write(' '.join(map(str, fields)) + '\n')
        session.process.stdin.flush()
        response = session.receive('REPLY').split()
        if CONTROL and sequence == 111:
            assert list(map(int, response[1:])) == [111, 0x80], response
            assert len(session.transactions) == 110
            session.transactions.append([False, 8, 9, 0x80])
            assert 'CONSUME before=c1 after=c1 reads=2 clears=1 ignore=1' in session.output
            assert sum(write and offset == 24 for write, _, offset, _ in session.transactions) == 1
            raise AssertionError('keyboard strobe clear missing')
        assert list(map(int, response[1:])) == [sequence, row[3]], response
        session.transactions.append(row)
        temporary = path.with_name(f'response-{sequence}.tmp')
        temporary.write_text(f'OK {row[3]}\n', encoding='ascii')
        temporary.replace(path.with_name(f'response-{sequence}.txt'))


def finish(session):
    assert session.receive('RECOVERY') == 'RECOVERY keyboard=42 pulses=3'
    inherited_finish(session)
    assert 'CONSUME before=d5 after=55 reads=2 clears=1 ignore=0' in session.output
    assert 'CONSUME before=c1 after=41 reads=2 clears=1 ignore=0' in session.output
    assert 'CONSUME before=c2 after=42 reads=2 clears=1 ignore=0' in session.output
    tail = (session.folder / 'instructions.txt').read_text().splitlines()[-13:]
    assert [line.split()[:2] for line in tail] == [
        ['fb65', '8d'], ['fb68', '20'], ['c83b', 'e6'], ['c83d', 'd0'],
        ['c841', 'ad'], ['c844', '10'], ['c846', '8d'], ['c849', '60'],
        ['fb6b', '8d'], ['fb6e', 'ad'], ['fb71', '8d'], ['fb74', '8d'],
        ['fb77', '4c']], tail
    if DEFERRED:
        expected = bytearray(session.scheduler_world)
        module.timer.BASE.put(expected, -0x96c, 0xff42, 4)
        module.timer.BASE.put(expected, -0x8ec, 1)
        assert (session.folder / 'deferred-world.bin').read_bytes() == expected
        assert (session.folder / 'deferred-code.bin').read_bytes() == (session.folder / 'service4-code.bin').read_bytes()
        assert (session.folder / 'deferred-state.bin').read_bytes() == struct.pack('>4I', 0x290800, 0x3f0000, 0x300000, 0xe00000)
        assert session.transactions[105] == [False, 8, 9, 0x80]
        assert session.transactions[110:] == [[False, 8, 9, 0], [True, 8, 24, 0x42]]


def main():
    global module, event_record, inherited_finish, CONTROL, DEFERRED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--control', action='store_true')
    parser.add_argument('--deferred', action='store_true')
    args = parser.parse_args()
    CONTROL = args.control
    DEFERRED = args.deferred
    if DEFERRED:
        sys.argv.remove('--deferred')
    os.environ['IIE_DEFERRED_KEY'] = str(int(DEFERRED))
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
    source = source.replace('local/experiments/card-event-live', 'local/experiments/card-keyboard-monitor')
    source = source.replace('IIE_BAD_EVENT', 'IIE_BAD_CONSUME')
    source = source.replace('event keyboard write missing', 'keyboard strobe clear missing')
    source = source.replace('== 64', '== ' + ('111' if DEFERRED else '106'))
    source = source.replace('EVENT write=1 keyboard=41', 'EVENT write=1 keyboard=c1')
    source = source.replace('EVENT write=2 keyboard=42', 'EVENT write=2 keyboard=c2')
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
    if DEFERRED:
        source = once(source,
            '[[False, 8, 9, 0], [True, 8, 24, 0x41], [False, 8, 9, 0], [True, 8, 24, 0x42],',
            '[[False, 8, 9, 0], [True, 8, 24, 0x41], [False, 8, 9, 0x80],')
        source = once(source, '\n\ndef scheduler_finish(session):',
            '\n    exchange_deferred(session, host)\n\n\ndef scheduler_finish(session):')
    source = once(source, '0x202650, 0x202730, 0x20284a', '0x202650, 0x20271e, 0x20284a')
    source = once(source, 'modeled event source with admitted type-3/type-5 live keyboard writes',
                  'modeled event source, test caller at FB65 invoking unmodified monitor input routine C83B and original host queue drains after busy-to-ready transition')
    source = once(source, 'timer delivery and admitted live event writes', 'CPU strobe consumption and host queue recovery')
    source = once(source, 'missing event keyboard write rejected', 'missing CPU strobe clear rejected')
    source = once(source, "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py',",
                  "[ROOT / 'fixtures/experiments/card-event-live/run.py', ROOT / 'fixtures/experiments/card-timer-delivery/run.py',")
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    event_record, inherited_finish = module.event_world, module.scheduler_finish
    module.event_world, module.scheduler_finish = recovery_world, finish
    module.check_reply, module.check_queued = check_reply, check_queued
    module.exchange_deferred = exchange_deferred
    path = HERE / f'{"control" if CONTROL else "results"}-{args.driver}-48.json'
    previous = path.read_bytes() if DEFERRED and path.exists() else None
    module.main()
    record = json.loads(path.read_text())
    run = record['runs'][0]
    origins = {}
    for name, digest in list(record['inputs_sha256'].items()):
        source_path = Path(name)
        if source_path.is_relative_to(ROOT / 'local/experiments/card-keyboard-monitor'):
            destination = Path(run['run_directory']) / 'inputs' / source_path.relative_to(ROOT / 'local/experiments/card-keyboard-monitor')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
            del record['inputs_sha256'][name]
            record['inputs_sha256'][str(destination)] = digest
            origins[str(destination)] = name
    record['input_snapshot_origins'] = origins
    run.update(vbl_callbacks=7, timer_callbacks_started=7, timer_callbacks_completed=7,
               admitted_callbacks=[4, 7], event_types=[3, 5], seeded_keyboard=0xd5,
               consumer='test caller selects internal ROM and invokes original C83B-C849 after seed and each host arrival',
               event_writes_forwarded=sum(write and offset == 24 for write, _, offset, _ in run['transactions']))
    run['deferred_drain'] = DEFERRED
    run['consumer_schedule'] = 'seed after transaction 70; first arrival after busy status transaction 106; second after transaction 112' if DEFERRED else 'seed after transaction 70; each real arrival before its host response'
    if DEFERRED:
        record['scope'] += '; busy observation retains second key through event completion; explicit later host caller invokes original queue drain at 2480'
    if DEFERRED:
        target = path.with_name(path.stem + '-deferred' + path.suffix)
        target.write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
        if previous is None:
            path.unlink()
        else:
            path.write_bytes(previous)
    else:
        path.write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
