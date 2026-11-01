#!/usr/bin/env python3
"""Check original PAGE1 mixed host execution with modeled PDS replies."""
import argparse
import json
import os
import subprocess
import time
import run as bridge
from prepare import once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=int, choices=(5, 6), required=True)
    parser.add_argument('--mixed', choices=('40', '80'), required=True)
    args = parser.parse_args()
    mode = (0x30 if args.driver == 6 or args.mixed == '80' else 0x20) | 4 | (8 if args.mixed == '80' else 0)
    _, _, inputs = bridge.prepare()
    data = bridge.oracle.raw_image()
    expected, _ = bridge.expected_transactions(252 if args.driver == 5 else 255, mode, data)
    folder = bridge.WORK / f'host-{args.driver}-{mode:02x}-{time.time_ns()}'
    folder.mkdir()
    model = folder / 'model.lua'
    rows = ',\n'.join('{' + ','.join(str(v).lower() for v in row) + '}' for row in expected)
    model.write_text('local rows = {\n' + rows + """\n}
local sequence = 0
return function(write, width, offset, value)
    sequence = sequence + 1
    local row = assert(rows[sequence], 'Unexpected host transaction')
    assert(row[1] == write and row[2] == width and row[3] == offset, 'Host transaction mismatch')
    assert(not write or row[4] == value, 'Host write mismatch')
    if sequence == #rows then
        local file = assert(io.open(os.getenv('IIE_DISPATCH_RUN') .. '/model-done.txt', 'w'))
        file:write(sequence)
        file:close()
    end
    return row[4]
end
""", encoding='ascii')
    host = folder / 'execute.lua'
    host.write_text(once((bridge.WORK / 'execute.lua').read_text(),
        "dofile('fixtures/experiments/card-hires-live-modes/bridge.lua')", f"dofile('{model.as_posix()}')"), encoding='ascii')
    snapshots, paths = bridge.snapshot_inputs()
    env = dict(os.environ, IIE_DISPATCH_RUN=folder.as_posix(),
        IIE_DISPATCH_CODE=(bridge.CODE / f'CODE_{args.driver}.bin').as_posix(), IIE_DISPATCH_SERVICE='1',
        IIE_INIT_WORLD=snapshots['card-display-init', args.driver, 'world.bin'].as_posix(),
        IIE_INIT_CODE=snapshots['card-display-init', args.driver, 'code-after.bin'].as_posix(),
        IIE_SWITCH_WORLD=snapshots['card-display-switches', args.driver, 'world.bin'].as_posix(),
        IIE_GLYPH_WORLD=snapshots['card-display-glyph', 0, 'world.bin'].as_posix(),
        IIE_MAIN_CODE=(bridge.CODE / 'CODE_1.bin').as_posix(),
        IIE_FRAME_SIZE=str((320 if args.driver == 5 else 80) * 480),
        IIE_WRONG_DESTINATION='0', IIE_BAD_GLYPH='0', IIE_GLYPH_BANK='0',
        IIE_BAD_REFRESH='0', IIE_TEXT_MODE=str(mode))
    command = [str(bridge.MAME), 'maclc', '-rompath', str(bridge.ROM.parent.parent), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '51', '-skip_gameinfo',
        '-cfg_directory', str(folder / 'cfg'), '-nvram_directory', str(folder / 'nvram'),
        '-snapshot_directory', str(folder / 'snap'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(host), '-autoboot_delay', '0', '-debug', '-debugger', 'none',
        '-debugscript', str(bridge.ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    with (folder / 'mame.log').open('w') as log:
        process = subprocess.Popen(command, cwd=bridge.ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            assert process.wait(timeout=15) == 0
            shutdown = 'exited_zero'
        except subprocess.TimeoutExpired:
            shutdown = 'timeout_after_guest_return'
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    assert '[LUA ERROR]' not in (folder / 'mame.log').read_text()
    assert int((folder / 'model-done.txt').read_text()) == len(expected)
    bridge.check_render(args.driver, folder, snapshots, mode, data, True)
    world, code = bridge.check_render(args.driver, folder, snapshots, mode, data, False)
    assert (folder / 'world.bin').read_bytes() == world
    assert (folder / 'code-after.bin').read_bytes() == code
    assert (folder / 'state.bin').read_bytes() == bytes.fromhex('0020281c003f0000')
    inputs += paths + [bridge.HERE / 'run.py', bridge.HERE / 'check-host.py', host, model,
        bridge.CODE / 'CODE_1.bin', bridge.CODE / f'CODE_{args.driver}.bin', bridge.ROM, bridge.MAME]
    result = {'scope': 'Original host execution with modeled PDS replies; no RTL, native memory or card RTI qualification',
        'driver': args.driver, 'mode': mode, 'transactions_checked': len(expected),
        'host_shutdown': shutdown, 'run_directory': str(folder),
        'hashes': {p.name: bridge.sha(p) for p in folder.iterdir() if p.suffix == '.bin' or p.name == 'trace.txt'},
        'inputs_sha256': {str(p): bridge.sha(p) for p in inputs}}
    (bridge.HERE / f'host-check-{args.driver}-{mode:02x}.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print(f'HOST ONLY PASS CODE {args.driver} mode {mode:02x}: both pixel/world snapshots and original return; modeled PDS replies')


if __name__ == '__main__':
    main()
