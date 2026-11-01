#!/usr/bin/env python3
"""Compose original callback reloads with visible service-4 cache updates."""
import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-reload-service4'
PARENT = ROOT / 'fixtures/experiments/card-reload-callback'
sys.path.insert(0, str(PARENT))
spec = importlib.util.spec_from_file_location('service4_prepare', HERE / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
once, sha = prepare.once, prepare.sha


def callback_runner():
    source = (PARENT / 'run.py').read_text()
    source = once(source, 'mode = 0xca if alternate else 0x4a',
                  'mode = 0xc8 if alternate else 0x48')
    source = once(source, '((False, -0x4012), (True, -0x5012))',
                  '((False, -0x4812), (True, -0x5812))')
    source = once(source, 'for offset in (-0x4012, -0x5012):',
                  'for offset in (-0x4812, -0x5812):')
    source = once(source, "    if control:\n        code[0x22:0x24] = bytes.fromhex('0338')\n", '')
    start = source.index("                if not control or str(error)")
    end = source.index('            if not rejected:', start)
    source = source[:start] + '''                if not control or str(error) != 'service4 pixel/guard mismatch':
                    raise
                rejected = str(error)
                assert len(session.transactions) == 19
''' + source[end:]
    marker = "    for offset in (0x35e, 0x3a0, 0x3ae, 0x3b6, 0x404):"
    source = once(source, marker, '    pcs = pcs[:pcs.index(0x202820)]\n' + marker)
    module = type(sys)('callback_page1')
    module.__file__ = str(PARENT / 'run.py')
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    module.HERE, module.WORK, module.Live = WORK, WORK, Live
    return module


def check_service4(folder, driver, mode):
    world = bytearray((folder / '2-world.bin').read_bytes())
    code = bytearray((folder / 'code-input.bin').read_bytes())
    main = bytearray(callback.text.page_data())
    transformed = bytes(value | 128 for value in code[0x1e14:0x1ebc])
    main[0x250:0x2f8] = transformed
    world[0x5960 - 0x88f] = 4
    world[0x5960 - 0x892] = 9
    world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
    pairs = bytes(value for item in transformed for value in (1, item))
    world[0x5960 - 0x4372:0x5960 - 0x4372 + len(pairs)] = pairs
    visible = {address for _, _, address in callback.text.visible_cells()}
    assert len(visible & set(range(0x650, 0x6f8))) == 160
    for address in visible:
        if 0x650 <= address < 0x6f8:
            world[0x5960 - 0x4812 + (address - 0x400) * 2] = 0
    callback.text.MODE, callback.text.GLYPH_BANK = mode, 0
    expected = callback.text.expected_frame(driver, main)
    actual = (folder / 'service4-frame.bin').read_bytes()
    if CONTROL:
        assert (folder / 'bad-cache-before.bin').read_bytes() == bytes([1, transformed[0]])
        assert (folder / 'bad-cache-after.bin').read_bytes() == bytes([1, transformed[0] ^ 1])
        world[0x5960 - 0x4371] ^= 1
        main[0x250] ^= 1
        assert actual == callback.text.expected_frame(driver, main), 'control pixel fault mismatch'
    actual_world = (folder / 'service4-world.bin').read_bytes()
    assert actual_world == world, 'service4 world mismatch: ' + str([
        (hex(i - 0x5960), a, b) for i, (a, b) in enumerate(zip(actual_world, world)) if a != b][:12])
    code[0x1e14:0x1ebc] = transformed
    assert (folder / 'service4-code.bin').read_bytes() == code
    assert (folder / 'service4-main.bin').read_bytes() == (callback.CODE / 'CODE_1.bin').read_bytes()
    assert (folder / 'service4-converted.bin').read_bytes() == (folder / '2-converted.bin').read_bytes()
    assert actual == expected, 'service4 pixel/guard mismatch'
    assert actual != (folder / '2-frame.bin').read_bytes(), 'service4 did not change pixels'
    return world


from live import Live as CallbackLive


class Live(CallbackLive):
    def exchange(self, host, profile, before_ack):
        super().exchange(host, profile, before_ack)
        expected = [[False, 8, 1, 224]] * 2 + [[False, 16, 4, 0xc07d], [False, 8, 12, 4]]
        expected += [[False, 8, 33, 40]] * 4 + [[True, 8, 12, 0]]
        for sequence, row in enumerate(expected, 12):
            path = self.folder / f'request-{sequence}.txt'
            deadline = time.monotonic() + 20
            while True:
                try:
                    fields = list(map(int, path.read_text().split()))
                    break
                except (FileNotFoundError, PermissionError):
                    assert host.poll() is None and time.monotonic() < deadline, 'Missing service4 request'
                    time.sleep(0.002)
            assert fields == [sequence, int(row[0]), row[1], row[2], row[3] if row[0] else 0], fields
            if sequence == 20:
                self.expected_world = check_service4(self.folder, DRIVER, MODE)
            self.process.stdin.write(' '.join(map(str, fields)) + '\n')
            self.process.stdin.flush()
            response = self.receive('REPLY').split()
            assert list(map(int, response[1:])) == [sequence, row[3]], response
            self.transactions.append(row)
            temporary = path.with_name(f'response-{sequence}.tmp')
            temporary.write_text(f'OK {row[3]}\n', encoding='ascii')
            temporary.replace(path.with_name(f'response-{sequence}.txt'))

    def finish(self):
        self.receive('PASS reload service4')
        assert self.process.wait(timeout=10) == 0
        assert (self.folder / 'final-world.bin').read_bytes() == self.expected_world
        assert (self.folder / 'final-state.bin').read_bytes() == bytes.fromhex('0020281c003f00000030000033445566')
        pcs = [int(p, 16) for p in re.findall(r'^([0-9A-F]{8}):', (self.folder / 'trace.txt').read_text(), re.M)]
        assert pcs.count(0x201ebc) == 1 and pcs.count(0x201ecc) == 168
        assert pcs.count(0x200a7e) == 4
        assert pcs.count(0x203e94 if DRIVER == 5 else 0x203e5c) == 5920


def main():
    global callback, DRIVER, MODE, CONTROL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--alternate', action='store_true')
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    DRIVER, MODE = args.driver, 0xc8 if args.alternate else 0x48
    CONTROL = args.control
    callback = callback_runner()
    sources, image, inputs = prepare.prepare()
    binary = WORK / 'bridge.vvp'
    command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
        '-Ptb_card_platform.FAST=1', '-o', callback.linux(binary), *map(callback.linux, sources)]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    os.environ['IIE_BAD_CACHE'] = str(int(args.control))
    result, snapshots = callback.execute(DRIVER, args.alternate, args.control, binary, image)
    acks = sum(write and offset == 12 for write, _, offset, _ in result['transactions'])
    assert acks == (1 if args.control else 2)
    result.update(acks_forwarded=acks, framebuffer_checks=3 if args.control else 4,
                  cache_pairs=168, visible_main_cells=160, dirty_holes=8)
    inputs += snapshots + sources + [HERE / 'run.py', PARENT / 'run.py', PARENT / 'execute.lua',
        PARENT / 'live.py', PARENT / 'resources.py', callback.TEXT / 'run.py', callback.COLOR / 'run.py',
        ROOT / 'fixtures/experiments/card-display-glyph/run.py',
        callback.CODE / 'CODE_1.bin', callback.CODE / 'CODE_5.bin', callback.CODE / 'CODE_6.bin', callback.ROM, callback.MAME]
    record = {'scope': 'Original callback reload 0/1/0 followed by live service4 PAGE1 main-cache update, visible pixels before second ACK and two card RTIs; injected display/settings state and modeled UI/resource operations',
              'runs': [result], 'inputs_sha256': {str(p): sha(p) for p in inputs}}
    name = f'{"control" if args.control else "results"}-{DRIVER}-{MODE:02x}.json'
    (HERE / name).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'PASS CODE {DRIVER} mode {MODE:02x}: ' + ('corrupt cache rejected before second ACK' if args.control else 'reload, visible service4 and two RTIs'))


if __name__ == '__main__':
    main()
