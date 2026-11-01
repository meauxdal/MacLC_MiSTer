#!/usr/bin/env python3
"""Check admitted type-3/type-5 events against the live keyboard latch."""
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


def event_world(world, phase):
    result = bytearray(world)
    result[0x5960 - 0x8e0:0x5960 - 0x8d0] = struct.pack(
        '>HIIIH', 3 if phase == 4 else 5, 0xff41 if phase == 4 else 0xff42,
        0x12345678, 0x00020003, 0)
    return result


def check_event(folder, phase, world):
    assert (folder / f'event-{phase}-trap.bin').read_bytes() == struct.pack('>2I', 0xfff7, 0x2ff720)
    assert (folder / f'event-{phase}-state.bin').read_bytes() == struct.pack(
        '>4I', 0x20284a, 0x3f0000, 0x300000, 0x33445566)
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
        phase_rows = rows + ([[True, 8, 24, 0x41 if phase == 4 else 0x42]] if phase in (4, 7) else [])
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
            if phase == 5 and lane == 0:
                check_event(session.folder, 4, session.event_before[4])
            if lane == 8:
                session.vbl_due = timer.BASE.check_callback(session.folder, phase, world)
                assert (session.folder / f'prime-{phase}-pending.bin').read_bytes() == bytes(1)
            if os.getenv('IIE_BAD_EVENT') == '1' and phase == 4 and lane == 11:
                assert fields == [sequence, 0, 8, 13, 0], fields
                check_event(session.folder, phase, session.event_before[phase])
                assert (session.folder / 'event-fault-code.bin').read_bytes() == (session.folder / 'service4-code.bin').read_bytes()
                assert (session.folder / 'event-fault-pc.bin').read_bytes() == struct.pack('>2I', 0x202730, 0x202734)
                assert len(session.transactions) == 64
                raise AssertionError('event keyboard write missing')
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
            if lane == 11:
                world = event_world(world, phase)
                session.scheduler_world = bytearray(world)
            if lane == 10 and phase in (4, 7):
                if not hasattr(session, 'event_before'):
                    session.event_before = {}
                session.event_before[phase] = bytearray(world)


def scheduler_finish(session):
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
    for pc in (0x202846, 0x2024aa, 0x20250c, 0x202650, 0x202730, 0x20284a):
        assert pcs.count(pc) == 2, (hex(pc), pcs.count(pc))
    assert [line for line in session.output if line.startswith('EVENT')] == [
        'EVENT write=1 keyboard=41', 'EVENT write=2 keyboard=42']


def main():
    source = (PARENT / 'run.py').read_text()
    assert source.count('local/experiments/card-timer-delivery') == 1
    source = source.replace('local/experiments/card-timer-delivery', 'local/experiments/card-event-live')
    source = once(source, '    source = source_path.read_text()',
                  "    source = source_path.read_text().replace('admitted_callbacks=[] if args.control', 'admitted_callbacks=[4] if args.control')")
    source = once(source, "source.replace(old, 'timer control bit mismatch')",
                  "source.replace(old, 'event keyboard write missing')")
    source = once(source, "'assert len(session.transactions) == 61')", "'assert len(session.transactions) == 64')")
    source = source.replace('IIE_BAD_TIMER', 'IIE_BAD_EVENT')
    os.environ['IIE_BAD_TIMER'] = '0'
    source = once(source, 'zero device countdowns; no event handler',
                  'zero device countdowns; modeled event source with admitted type-3/type-5 live keyboard writes')
    source = once(source, 'missing timer bit-set rejected before polling', 'missing event keyboard write rejected')
    source = once(source, 'timer delivery, VBL handshake and polling admission', 'timer delivery and admitted live event writes')
    source = once(source, 'timer_callbacks_completed=4 if args.control else 7,',
                  'timer_callbacks_completed=4 if args.control else 7, event_types=[3] if args.control else [3, 5], event_writes_forwarded=0 if args.control else 2,')
    source = once(source, "    BASE.main()", "    BASE.scheduler_finish = scheduler_finish\n    BASE.main()")
    source = once(source, "[ROOT / 'fixtures/experiments/card-vbl-admission/run.py',",
                  "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py', ROOT / 'fixtures/experiments/card-vbl-admission/run.py',")
    timer.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), timer.__dict__)
    timer.scheduler_exchange, timer.scheduler_finish = scheduler_exchange, scheduler_finish
    timer.main()


if __name__ == '__main__':
    main()
