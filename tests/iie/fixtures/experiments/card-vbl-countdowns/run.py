#!/usr/bin/env python3
"""Check device countdown expiration and callback dispatch over live PDS."""
import importlib.util
import os
from pathlib import Path
import re
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = HERE.parent / 'card-timer-delivery'
spec = importlib.util.spec_from_file_location('countdown_candidate', HERE / 'prepare.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


def check_install(folder):
    world = original_install(folder)
    for device, (count, reload) in enumerate(zip(candidate.INITIAL, candidate.RELOAD)):
        BASE.put(world, -0x1366 + device * 2, count)
        BASE.put(world, -0x1336 + device * 2, reload)
        BASE.put(world, -0x13ea + device * 4, 0x320000 + device * 0x100, 4)
        BASE.put(world, -0x140a + device * 4, 0x330000 + device * 0x100, 4)
    return world


def check_callback(folder, phase, world):
    calls = []
    stubs = bytearray(0x800)
    for device in range(8):
        stubs[device * 0x100 + 0x20:device * 0x100 + 0x26] = bytes.fromhex('74ff76ff4e75')
    assert (folder / f'device-{phase}-stubs.bin').read_bytes() == stubs
    for device in reversed(range(8)):
        offset = 0x5960 - 0x1366 + device * 2
        count = int.from_bytes(world[offset:offset + 2], 'big')
        expire = count == 1
        if count:
            BASE.put(world, -0x1366 + device * 2,
                     candidate.RELOAD[device] if expire else (count - 1) & 0xffff)
        path = folder / f'device-{phase}-{device}.bin'
        omitted = os.getenv('IIE_BAD_COUNTDOWN') == '1' and phase == 4 and device == 4
        if expire and not omitted:
            d1, d2, a0, a3, sp = struct.unpack('>5I', path.read_bytes())
            assert (d1 & 0xffff, d2, a0, a3, sp) == (
                (0xc0 | device) << 8, device, 0x320000 + device * 0x100,
                0x330000 + device * 0x100, 0x3dffd0)
            calls.append(device)
        else:
            assert not path.exists(), (phase, device)
    due = original_callback(folder, phase, world)
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    expected = [0x320020 + slot * 0x100 for slot in calls]
    actual = [pc for pc in pcs if pc in range(0x320020, 0x320800, 0x100)]
    global CALLS
    CALLS += expected
    assert actual == CALLS, (actual, CALLS)
    return due


def check_timer(folder, phase, world):
    original_timer(folder, phase, world)
    pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (folder / 'trace.txt').read_text(), re.M)]
    assert pcs.count(0x2848f6) == phase * 8
    if os.getenv('IIE_BAD_COUNTDOWN') == '1' and phase == 4:
        assert (folder / 'countdown-fault-main.bin').read_bytes() == (
            ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin').read_bytes()
        assert (folder / 'countdown-fault-pc.bin').read_bytes() == struct.pack('>2I', 0x284926, 0x28492a)
        raise AssertionError('device countdown callback mismatch')


def main():
    global BASE, original_install, original_callback, original_timer, CALLS
    CALLS = []
    source = (PARENT / 'run.py').read_text()
    source = source.replace('local/experiments/card-timer-delivery', 'local/experiments/card-vbl-countdowns')
    source = source.replace('timer control bit mismatch', 'device countdown callback mismatch')
    source = source.replace('len(session.transactions) == 61', 'len(session.transactions) == 63')
    source = source.replace("os.environ['IIE_BAD_TIMER'] = str(int(args.control))",
        "os.environ['IIE_BAD_TIMER'] = '0'\\\\n    os.environ['IIE_BAD_COUNTDOWN'] = str(int(args.control))")
    source = source.replace("'Original installed timer callback delivery after each VBL, live control-bit handshake and polling admission after reload/service4; modeled VBL/Time Manager queues and callback delivery, zero device countdowns; no event handler'",
        "'Original installed VBL device countdowns and dispatch, timer handshake and polling admission over live PDS; seeded device tables and clobbering synthetic callbacks, modeled OS scheduling'")
    source = source.replace('missing timer bit-set rejected before polling', 'missing device callback rejected before polling')
    source = source.replace('timer delivery, VBL handshake and polling admission', 'device countdowns, dispatch and timer handshake')
    source = candidate.once(source,
        "[ROOT / 'fixtures/experiments/card-vbl-admission/run.py', ROOT / 'fixtures/experiments/card-reload-service4/run.py', HERE / 'run.py',",
        "[ROOT / 'fixtures/experiments/card-timer-delivery/run.py', ROOT / 'fixtures/experiments/card-vbl-admission/run.py', ROOT / 'fixtures/experiments/card-reload-service4/run.py', HERE / 'run.py',")
    source = candidate.once(source, '    BASE.main()', '''    global original_install, original_callback, original_timer
    original_install, original_callback = BASE.check_install, BASE.check_callback
    original_timer = check_timer
    BASE.check_install, BASE.check_callback = countdown_install, countdown_callback
    globals()['check_timer'] = countdown_timer
    BASE.main()''')
    namespace = dict(__file__=str(HERE / 'run.py'), __name__='countdown_runner',
        countdown_install=check_install, countdown_callback=check_callback, countdown_timer=check_timer)
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), namespace)
    # The inherited main constructs BASE before invoking the callbacks.
    def install(folder):
        global BASE, original_install, original_callback, original_timer
        BASE = namespace['BASE']
        original_install = namespace['original_install']
        original_callback = namespace['original_callback']
        original_timer = namespace['original_timer']
        return check_install(folder)
    namespace['countdown_install'] = install
    namespace['main']()


if __name__ == '__main__':
    main()
