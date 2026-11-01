#!/usr/bin/env python3
"""Check original VBL installation, cadence and polling admission over live PDS."""
import os
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-reload-service4'
WORK = ROOT / 'local/experiments/card-vbl-admission'


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def put(world, offset, value, size=2):
    world[0x5960 + offset:0x5960 + offset + size] = value.to_bytes(size, 'big')


def check_install(folder):
    world = bytearray((folder / 'final-world.bin').read_bytes())
    put(world, -0x8aa, 0x300000, 4)
    put(world, -0x8ae, 3)
    put(world, -0x8ac, 0)
    put(world, -0x8a0, 0x2848ae, 4)
    put(world, -0x8b4, 0x28489a, 4)
    assert (folder / 'install-world.bin').read_bytes() == world, 'VBL installation world mismatch'
    assert (folder / 'install-vbl.bin').read_bytes() == struct.pack('>2I', 0x300000 - 0x8a6, 3)
    assert (folder / 'install-timer.bin').read_bytes() == struct.pack('>2I', 0x300000 - 0x8ba, 0)
    assert (folder / 'install-state.bin').read_bytes() == struct.pack('>4I', 0x290400, 0x3f0000, 0x300000, 0x33445566)
    for index in range(8):
        put(world, -0x1366 + index * 2, 0)
    return world


def check_callback(folder, phase, world):
    counter = int.from_bytes(world[0x5960 - 0x8ae:0x5960 - 0x8ac], 'big') - 1
    due = counter < 0
    if due:
        counter += 3
    put(world, -0x8ae, counter)
    put(world, -0x89c, 1)
    put(world, -0x8ac, 255 if due else 0)
    actual = (folder / f'vbl-{phase}-world.bin').read_bytes()
    assert (folder / f'vbl-{phase}-state.bin').read_bytes() == struct.pack(
        '>4I', 0x290420 + (phase - 1) * 0x20, 0x3e0004, 0x33445500, 0x33445566)
    assert (folder / f'vbl-{phase}-registers.bin').read_bytes() == struct.pack('>9I',
        0x11223303, 0x11223304, 0x11223305, 0x11223306, 0x11223307,
        0x22334402, 0x22334403, 0x22334404, 0x33445500)
    assert (folder / f'prime-{phase}.bin').read_bytes() == struct.pack('>2I', 0x300000 - 0x8ba, 4)
    if os.getenv('IIE_BAD_VBL') == '1' and phase == 4:
        fault = bytearray(world)
        put(fault, -0x8ac, 0)
        assert actual == fault, 'unexpected VBL control fault'
        raise AssertionError('VBL admission flag mismatch')
    assert actual == world, 'VBL callback world mismatch'
    return due


def scheduler_exchange(session, host, profile):
    assert (profile & 3) == 2
    rows = [[False, 8, 13, 0xaa], [True, 8, 13, 0xaa],
        [False, 8, 13, 0xaa], [False, 16, 28, 0xbeef], [False, 8, 8, 0],
        [True, 16, 28, 0xbeef], [False, 8, 13, 0xaa], [True, 8, 13, 0xaa], [False, 8, 1, 0]]
    world = None
    for sequence in range(21, 84):
        path = session.folder / f'request-{sequence}.txt'
        deadline = time.monotonic() + 20
        while True:
            try:
                fields = list(map(int, path.read_text().split()))
                break
            except (FileNotFoundError, PermissionError):
                assert host.poll() is None and time.monotonic() < deadline, 'Missing VBL request'
                time.sleep(0.002)
        row = rows[(sequence - 21) % 9]
        if sequence == 21:
            row = [False, 8, 13, 0xea]
        assert fields == [sequence, int(row[0]), row[1], row[2], row[3] if row[0] else 0], fields
        if world is None:
            world = check_install(session.folder)
        if (sequence - 21) % 9 == 8:
            phase = (sequence - 21) // 9 + 1
            session.vbl_due = check_callback(session.folder, phase, world)
        session.process.stdin.write(' '.join(map(str, fields)) + '\n')
        session.process.stdin.flush()
        response = session.receive('REPLY').split()
        assert list(map(int, response[1:])) == [sequence, row[3]], response
        session.transactions.append(row)
        temporary = path.with_name(f'response-{sequence}.tmp')
        temporary.write_text(f'OK {row[3]}\n', encoding='ascii')
        temporary.replace(path.with_name(f'response-{sequence}.txt'))
        if (sequence - 21) % 9 == 8:
            if session.vbl_due:
                put(world, -0x8ac, 0)
                previous = int.from_bytes(world[0x5960 - 0x8bc:0x5960 - 0x8ba], 'big')
                put(world, -0x8bc, previous + 1)
            session.scheduler_world = bytearray(world)


def scheduler_finish(session):
    for phase in range(1, 8):
        due = phase in (4, 7)
        callback_world = bytearray((session.folder / f'vbl-{phase}-world.bin').read_bytes())
        if due:
            put(callback_world, -0x8ac, 0)
            previous = int.from_bytes(callback_world[0x5960 - 0x8bc:0x5960 - 0x8ba], 'big')
            put(callback_world, -0x8bc, previous + 1)
        assert (session.folder / f'poll-{phase}-world.bin').read_bytes() == callback_world
        assert (session.folder / f'poll-{phase}-state.bin').read_bytes() == struct.pack(
            '>4I', 0x202846 if due else 0x202832, 0x3f0000, 0x300000, 0x33445566)
    assert (session.folder / 'scheduler-world.bin').read_bytes() == session.scheduler_world
    for suffix, previous in (('frame', 'service4-frame'), ('code', 'service4-code'),
                             ('main', 'service4-main'), ('converted', 'service4-converted')):
        assert (session.folder / f'scheduler-{suffix}.bin').read_bytes() == (session.folder / f'{previous}.bin').read_bytes()


def main():
    source = (PARENT / 'run.py').read_text()
    source = once(source, "WORK = ROOT / 'local/experiments/card-reload-service4'",
                  "WORK = ROOT / 'local/experiments/card-vbl-admission'")
    source = once(source, "if not control or str(error) != 'service4 pixel/guard mismatch':",
                  "if not control or str(error) != 'VBL admission flag mismatch':")
    source = once(source, 'assert len(session.transactions) == 19', 'assert len(session.transactions) == 55')
    source = once(source, '    def finish(self):',
                  '        scheduler_exchange(self, host, profile)\n\n    def finish(self):\n        scheduler_finish(self)')
    source = once(source, "self.receive('PASS reload service4')", "self.receive('PASS VBL admission')")
    source = once(source, 'CONTROL = args.control', 'CONTROL = False')
    source = once(source, "os.environ['IIE_BAD_CACHE'] = str(int(args.control))",
                  "os.environ['IIE_BAD_CACHE'] = '0'\n    os.environ['IIE_BAD_VBL'] = str(int(args.control))")
    source = once(source, 'assert acks == (1 if args.control else 2)', 'assert acks == 2')
    source = once(source, 'framebuffer_checks=3 if args.control else 4,',
                  'framebuffer_checks=4, vbl_callbacks=4 if args.control else 7, admitted_callbacks=[] if args.control else [4, 7],')
    source = once(source, "inputs += snapshots + sources + [HERE / 'run.py',",
                  "inputs += snapshots + sources + [ROOT / 'fixtures/experiments/card-reload-service4/run.py', HERE / 'run.py',")
    source = once(source, "'scope': 'Original callback reload 0/1/0 followed by live service4 PAGE1 main-cache update, visible pixels before second ACK and two card RTIs; injected display/settings state and modeled UI/resource operations'",
                  "'scope': 'Original VBL installer, installed callback cadence and polling admission after live reload/service4; modeled VBL/Time Manager traps, zero device countdowns and injected callback delivery; no event handler or timed text flashing'")
    source = once(source, "'corrupt cache rejected before second ACK' if args.control else 'reload, visible service4 and two RTIs'",
                  "'missing VBL flag rejected before polling' if args.control else 'installed VBL cadence and polling admission'")
    module = type(sys)('vbl_runner')
    module.__file__ = str(HERE / 'run.py')
    module.scheduler_exchange, module.scheduler_finish = scheduler_exchange, scheduler_finish
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
