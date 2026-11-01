#!/usr/bin/env python3
"""Check admitted non-keyboard callbacks and their live register tail."""
import importlib.util
import os
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-timer-delivery'
spec = importlib.util.spec_from_file_location('event_timer_runner', PARENT / 'run.py')
timer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timer)
once = timer.once


def setup_tables(world):
    put = timer.BASE.put
    event_type = int(os.environ['IIE_PATH_EVENT'])
    for slot in range(24):
        put(world, -0x1396 + slot * 2, 0)
    put(world, -0x1394, 1 << ((event_type + 1) % 16))
    for index, slot in enumerate((20, 7, 0)):
        put(world, -0x1396 + slot * 2, 1 << event_type)
        put(world, -0x13ea + slot * 4, 0x320000 + index * 0x100, 4)
        put(world, -0x140a + slot * 4, 0x330000 + slot * 0x100, 4)


def check_handlers(folder, phase, control=False):
    handlers = bytearray(0x300)
    for index, slot in enumerate((20, 7, 0)):
        handlers[index * 0x100 + 0x1c:index * 0x100 + 0x22] = bytes.fromhex('70ff76ff4e75')
        path = folder / f'handler-{phase}-{slot}.bin'
        if control and slot == 7:
            assert not path.exists(), 'omitted handler executed'
            continue
        actual = struct.unpack('>7I', path.read_bytes())
        assert actual == (int(os.environ['IIE_PATH_EVENT']), (0xc0 | slot) << 8,
                          slot, 0x320000 + index * 0x100, 0x2ff720,
                          0x330000 + slot * 0x100, 0x3efff0), actual
    assert (folder / f'event-{phase}-handlers.bin').read_bytes() == handlers


def event_world(world, phase):
    result = bytearray(world)
    count = int.from_bytes(result[0x5960 - 0x106e:0x5960 - 0x106c], 'big')
    timer.BASE.put(result, -0x106e, count + 1)
    result[0x5960 - 0x8e0:0x5960 - 0x8d0] = struct.pack(
        '>HIIIH', int(os.environ['IIE_PATH_EVENT']), 0xff41,
        0x12345678, 0x00020003, 0)
    return result


def check_event(folder, phase, world):
    assert (folder / f'event-{phase}-trap.bin').read_bytes() == struct.pack('>2I', 0xfff7, 0x2ff720)
    assert (folder / f'event-{phase}-state.bin').read_bytes() == struct.pack(
        '>4I', 0x20284a, 0x3f0000, 0x300000, 0x33445566)
    check_handlers(folder, phase)
    actual = (folder / f'event-{phase}-world.bin').read_bytes()
    assert actual == event_world(world, phase), 'event world mismatch: ' + str([
        (hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual, event_world(world, phase))) if a != b][:12])


def scheduler_exchange(session, host, profile):
    assert (profile & 3) == 2
    rows = [[False, 8, 13, 0xea], [True, 8, 13, 0xaa],
        [False, 8, 13, 0xaa], [False, 16, 28, 0xbeef], [False, 8, 8, 0],
        [True, 16, 28, 0xbeef], [False, 8, 13, 0xaa], [True, 8, 13, 0xaa],
        [False, 8, 13, 0xaa], [True, 8, 13, 0xea], [False, 8, 1, 0]]
    world, sequence = None, 20
    for phase in range(1, 8):
        base = 0xea if phase <= 4 else 0x6a
        phase_rows = [list(row) for row in rows]
        for row in phase_rows:
            if row[2] == 13:
                row[3] = base if row[3] == 0xea else base & ~0x40
        if phase in (4, 7):
            phase_rows += [[False, 8, 32, 136], [True, 8, 32, 136],
                           [False, 8, 13, base], [True, 8, 13, 0x6a]]
        for lane, row in enumerate(phase_rows):
            sequence += 1
            path = session.folder / f'request-{sequence}.txt'
            deadline = time.monotonic() + 20
            while True:
                try:
                    fields = list(map(int, path.read_text().split()))
                    break
                except (FileNotFoundError, PermissionError):
                    assert host.poll() is None and time.monotonic() < deadline, 'Missing event request'
                    time.sleep(0.002)
            if world is None:
                world = timer.BASE.check_install(session.folder)
                timer.BASE.put(world, -0x874, 0)
                timer.BASE.put(world, -0x87a, 0)
                setup_tables(world)
            if phase == 5 and lane == 0:
                check_event(session.folder, 4, session.event_before[4])
            if lane == 8:
                session.vbl_due = timer.BASE.check_callback(session.folder, phase, world)
                assert (session.folder / f'prime-{phase}-pending.bin').read_bytes() == bytes(1)
            if os.getenv('IIE_BAD_PATH') == '1' and phase == 4 and lane == 11:
                assert fields == [sequence, 0, 8, 32, 0], fields
                check_handlers(session.folder, phase, control=True)
                assert (session.folder / f'event-{phase}-pretail-world.bin').read_bytes() == event_world(session.event_before[phase], phase)
                assert (session.folder / 'event-fault-code.bin').read_bytes() == (session.folder / 'service4-code.bin').read_bytes()
                assert (session.folder / 'event-fault-pc.bin').read_bytes() == struct.pack('>2I', 0x2025d8, 0x2025dc)
                assert len(session.transactions) == 64
                raise AssertionError('event handler missing')
            assert fields == [sequence, int(row[0]), row[1], row[2], row[3] if row[0] else 0], fields
            if lane == 10:
                timer.check_timer(session.folder, phase, world)
            session.process.stdin.write(' '.join(map(str, fields)) + '\n')
            session.process.stdin.flush()
            response = session.receive('REPLY').split()
            assert list(map(int, response[1:])) == [sequence, row[3]], response
            session.transactions.append(row)
            temporary = path.with_name(f'response-{sequence}.tmp')
            temporary.write_text(f'OK {row[3]}\n', encoding='ascii')
            temporary.replace(path.with_name(f'response-{sequence}.txt'))
            if lane == 10:
                if session.vbl_due:
                    timer.BASE.put(world, -0x8ac, 0)
                    previous = int.from_bytes(world[0x5960 - 0x8bc:0x5960 - 0x8ba], 'big')
                    timer.BASE.put(world, -0x8bc, previous + 1)
                session.scheduler_world = bytearray(world)
            if lane == 14:
                world = event_world(world, phase)
                session.scheduler_world = bytearray(world)
            if lane == 10 and phase in (4, 7):
                if not hasattr(session, 'event_before'):
                    session.event_before = {}
                session.event_before[phase] = bytearray(world)


def scheduler_finish(session):
    session.receive('EVENT')
    for phase in range(1, 8):
        world = bytearray((session.folder / f'vbl-{phase}-world.bin').read_bytes())
        if phase in (4, 7):
            timer.BASE.put(world, -0x8ac, 0)
            count = int.from_bytes(world[0x5960 - 0x8bc:0x5960 - 0x8ba], 'big')
            timer.BASE.put(world, -0x8bc, count + 1)
            check_event(session.folder, phase, world)
        assert (session.folder / f'poll-{phase}-world.bin').read_bytes() == world
        assert (session.folder / f'poll-{phase}-state.bin').read_bytes() == struct.pack(
            '>4I', 0x202846 if phase in (4, 7) else 0x202832, 0x3f0000, 0x300000, 0x33445566)
    assert (session.folder / 'scheduler-world.bin').read_bytes() == session.scheduler_world
    for suffix, previous in (('frame', 'service4-frame'), ('code', 'service4-code'),
                             ('main', 'service4-main'), ('converted', 'service4-converted')):
        assert (session.folder / f'scheduler-{suffix}.bin').read_bytes() == (session.folder / f'{previous}.bin').read_bytes()
    pcs = [int(pc, 16) for pc in re.findall(r'^([0-9A-F]{8}):', (session.folder / 'trace.txt').read_text(), re.M)]
    for pc in (0x202846, 0x2024aa, 0x20250c, 0x2025ac, 0x2025f4, 0x202610, 0x202634, 0x20284a):
        assert pcs.count(pc) == 2, (hex(pc), pcs.count(pc))
    assert pcs.count(0x2025ae) == 48
    order = [slot for pc in pcs for index, slot in enumerate((20, 7, 0))
             if pc == 0x32001c + index * 0x100]
    assert order == [20, 7, 0] * 2, order
    assert [line for line in session.output if line.startswith('EVENT')] == ['EVENT commands=2 controls=2']


def main():
    source = (PARENT / 'run.py').read_text()
    assert source.count('local/experiments/card-timer-delivery') == 1
    source = source.replace('local/experiments/card-timer-delivery', 'local/experiments/card-event-paths-live')
    source = once(source, '    source = source_path.read_text()',
                  "    source = source_path.read_text().replace('admitted_callbacks=[] if args.control', 'admitted_callbacks=[4] if args.control')")
    source = once(source, "source.replace(old, 'timer control bit mismatch')",
                  "source.replace(old, 'event handler missing')")
    source = once(source, "'assert len(session.transactions) == 61')", "'assert len(session.transactions) == 64')")
    source = source.replace('IIE_BAD_TIMER', 'IIE_BAD_PATH')
    os.environ['IIE_BAD_TIMER'] = '0'
    source = once(source, 'zero device countdowns; no event handler',
                  'zero device countdowns; modeled non-keyboard event source and handler tables; synthetic callback stubs; admitted original dispatch and live register tail')
    source = once(source, 'missing timer bit-set rejected before polling', 'missing event callback rejected before live tail')
    source = once(source, 'timer delivery, VBL handshake and polling admission', 'timer delivery, admitted callback dispatch and live register tail')
    source = once(source, 'timer_callbacks_completed=4 if args.control else 7,',
                  'timer_callbacks_completed=4 if args.control else 7, event_type=int(os.environ["IIE_PATH_EVENT"]), handler_calls=2 if args.control else 6, event_tails_forwarded=0 if args.control else 2,')
    source = once(source, "    BASE.main()", "    BASE.scheduler_finish = scheduler_finish\n    BASE.main()")
    source = once(source, "[ROOT / 'fixtures/experiments/card-vbl-admission/run.py',",
                  "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py', ROOT / 'fixtures/experiments/card-vbl-admission/run.py',")
    timer.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), timer.__dict__)
    timer.scheduler_exchange, timer.scheduler_finish = scheduler_exchange, scheduler_finish
    timer.main()
    driver = sys.argv[sys.argv.index('--driver') + 1]
    prefix = 'control' if '--control' in sys.argv else 'results'
    original = HERE / f'{prefix}-{driver}-48.json'
    original.replace(HERE / f'{prefix}-{driver}-{os.environ["IIE_PATH_EVENT"]}.json')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--event', type=int, choices=(1, 2, 11), default=1)
    args, rest = parser.parse_known_args()
    os.environ['IIE_PATH_EVENT'] = str(args.event)
    sys.argv = [sys.argv[0], *rest]
    main()
