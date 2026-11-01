#!/usr/bin/env python3
"""Deliver the installed timer callback between original VBL and polling."""
import os
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-vbl-admission'


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def check_timer(folder, phase, world):
    assert (folder / f'timer-{phase}-world.bin').read_bytes() == world, 'timer changed host world'
    assert (folder / f'timer-{phase}-state.bin').read_bytes() == struct.pack(
        '>4I', 0x290600 + (phase - 1) * 0x20, 0x3d0004, 0x55667700, 0x33445566)
    assert (folder / f'timer-{phase}-registers.bin').read_bytes() == struct.pack('>9I',
        0x11223303, 0x11223304, 0x11223305, 0x11223306, 0x11223307,
        0x22334402, 0x22334403, 0x22334404, 0x55667700)
    assert (folder / f'timer-{phase}-addresses.bin').read_bytes() == struct.pack('>2I', 0xe00000, 0x2ff746)
    assert (folder / f'timer-{phase}-delivery.bin').read_bytes() == struct.pack('>3I', 0x2ff746, 0x28489a, 1)
    assert (folder / f'timer-{phase}-pending.bin').read_bytes() == bytes(1)


def scheduler_exchange(session, host, profile):
    assert (profile & 3) == 2
    rows = [[False, 8, 13, 0xea], [True, 8, 13, 0xaa],
        [False, 8, 13, 0xaa], [False, 16, 28, 0xbeef], [False, 8, 8, 0],
        [True, 16, 28, 0xbeef], [False, 8, 13, 0xaa], [True, 8, 13, 0xaa],
        [False, 8, 13, 0xaa], [True, 8, 13, 0xea], [False, 8, 1, 0]]
    world = None
    for sequence in range(21, 98):
        path = session.folder / f'request-{sequence}.txt'
        deadline = time.monotonic() + 20
        while True:
            try:
                fields = list(map(int, path.read_text().split()))
                break
            except (FileNotFoundError, PermissionError):
                assert host.poll() is None and time.monotonic() < deadline, 'Missing timer request'
                time.sleep(0.002)
        lane = (sequence - 21) % 11
        phase = (sequence - 21) // 11 + 1
        row = rows[lane]
        if world is None:
            world = BASE.check_install(session.folder)
        if lane == 8:
            session.vbl_due = BASE.check_callback(session.folder, phase, world)
            assert (session.folder / f'prime-{phase}-pending.bin').read_bytes() == bytes(1)
        if os.getenv('IIE_BAD_TIMER') == '1' and phase == 4 and lane == 8:
            assert fields == [sequence, 0, 8, 1, 0], 'unexpected timer control fault'
            check_timer(session.folder, phase, world)
            assert (session.folder / 'timer-fault-main.bin').read_bytes() == (
                ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin').read_bytes()
            assert (session.folder / 'timer-fault-pc.bin').read_bytes() == struct.pack('>2I', 0x2848a4, 0x2848aa)
            assert len(session.transactions) == 61
            raise AssertionError('timer control bit mismatch')
        assert fields == [sequence, int(row[0]), row[1], row[2], row[3] if row[0] else 0], fields
        if lane == 10:
            check_timer(session.folder, phase, world)
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
                BASE.put(world, -0x8ac, 0)
                previous = int.from_bytes(world[0x5960 - 0x8bc:0x5960 - 0x8ba], 'big')
                BASE.put(world, -0x8bc, previous + 1)
            session.scheduler_world = bytearray(world)


def main():
    global BASE
    source_path = PARENT / 'run.py'
    source = source_path.read_text()
    old = 'local/experiments/card-vbl-admission'
    assert source.count(old) == 2
    source = source.replace(old, 'local/experiments/card-timer-delivery')
    old = 'VBL admission flag mismatch'
    assert source.count(old) == 2
    source = source.replace(old, 'timer control bit mismatch')
    source = once(source, 'assert len(session.transactions) == 55', 'assert len(session.transactions) == 61')
    source = once(source, "os.environ['IIE_BAD_VBL'] = str(int(args.control))",
                  "os.environ['IIE_BAD_VBL'] = '0'\\n    os.environ['IIE_BAD_TIMER'] = str(int(args.control))")
    source = once(source, 'vbl_callbacks=4 if args.control else 7,',
                  'vbl_callbacks=4 if args.control else 7, timer_callbacks_started=4 if args.control else 7, timer_callbacks_completed=4 if args.control else 7,')
    source = once(source, "[ROOT / 'fixtures/experiments/card-reload-service4/run.py', HERE / 'run.py',",
                  "[ROOT / 'fixtures/experiments/card-vbl-admission/run.py', ROOT / 'fixtures/experiments/card-reload-service4/run.py', HERE / 'run.py',")
    source = once(source,
        'Original VBL installer, installed callback cadence and polling admission after live reload/service4; modeled VBL/Time Manager traps, zero device countdowns and injected callback delivery; no event handler or timed text flashing',
        'Original installed timer callback delivery after each VBL, live control-bit handshake and polling admission after reload/service4; modeled VBL/Time Manager queues and callback delivery, zero device countdowns; no event handler')
    source = once(source, 'missing VBL flag rejected before polling', 'missing timer bit-set rejected before polling')
    source = once(source, 'installed VBL cadence and polling admission', 'timer delivery, VBL handshake and polling admission')
    BASE = type(sys)('timer_runner')
    BASE.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(source_path), 'exec'), BASE.__dict__)
    BASE.scheduler_exchange = scheduler_exchange
    BASE.main()


if __name__ == '__main__':
    main()
