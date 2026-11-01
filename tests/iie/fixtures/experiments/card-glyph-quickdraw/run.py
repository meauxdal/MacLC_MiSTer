#!/usr/bin/env python3
"""Execute original glyph construction with live Macintosh toolbox traps."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-glyph-quickdraw'
TOOLS = Path('C:/Users/Elle/Downloads/mame0289b_x64')
SOURCE = ROOT / 'local/hardfiles/Apple-II_100MB.hda'
STARTUP = ROOT / 'local/experiments/firmware-memory/v221/Apple IIe Card 2.2.1.image'
CODE = ROOT / 'local/experiments/firmware-memory/code/CODE_2.bin'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    run = WORK / str(time.time_ns())
    run.mkdir(parents=True)
    original = sha(SOURCE)
    disk = run / 'autostart.hda'
    shutil.copyfile(SOURCE, disk)
    rb = ROOT / 'local/experiments/system-baseline/rb/rb-cli.exe'
    subprocess.run([str(rb), 'cp', str(STARTUP), '/IIe Startup', str(disk),
                    '/System 7.1.2/Startup Items/IIe Startup'], check=True, timeout=15)
    chd = run / 'autostart.chd'
    subprocess.run([str(TOOLS / 'chdman.exe'), 'createhd', '-i', str(disk), '-o', str(chd),
                    '-c', 'none', '-chs', '6403,1,32', '-ss', '512'], check=True, timeout=15,
                   stdout=subprocess.DEVNULL)
    command = [str(TOOLS / 'mame.exe'), 'maclc', '-rompath',
        str(ROOT / 'local/experiments/system-baseline/roms'), '-hard', str(chd), '-ramsize', '4M',
        '-video', 'none', '-sound', 'none', '-nothrottle', '-seconds_to_run', '85',
        '-skip_gameinfo', '-cfg_directory', str(run / 'cfg'), '-nvram_directory', str(run / 'nvram'),
        '-snapshot_directory', str(run / 'capture'), '-noreadconfig', '-nowriteconfig',
        '-autoboot_script', str(HERE / 'execute.lua'), '-autoboot_delay', '0',
        '-debug', '-debugger', 'none', '-debugscript',
        str(ROOT / 'fixtures/experiments/startup-discovery/debug.cmd')]
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, IIE_QD_RUN=run.as_posix()),
                            capture_output=True, text=True, timeout=30)
    (run / 'mame.log').write_text(result.stdout + result.stderr, encoding='ascii')
    assert sha(SOURCE) == original
    assert result.returncode == 0 and '[LUA ERROR]' not in result.stdout + result.stderr
    assert (run / 'code-before.bin').read_bytes() == CODE.read_bytes()
    assert (run / 'code-after.bin').read_bytes() == CODE.read_bytes()
    caller = struct.unpack('>III', (run / 'caller.bin').read_bytes())
    state = struct.unpack('>5I', (run / 'result.bin').read_bytes())
    assert state[:3] == caller and state[3:] == (128, 1024), state
    glyph = (run / 'glyph.bin').read_bytes()
    assert len(glyph) == 4096
    sys.path.insert(0, str(HERE.parent / 'card-monitor-prompt-render'))
    from prepare import text_oracle
    oracle, glyph_inputs = text_oracle()
    expected = bytearray(oracle['glyph_state']())
    expected[32 * 16:33 * 16] = bytes(16)
    expected[160 * 16:161 * 16] = bytes.fromhex('01fc') * 8
    assert glyph == expected, 'real QuickDraw glyph mismatch'
    print('QuickDraw space:', glyph[32 * 16:33 * 16].hex())
    print('QuickDraw A:', glyph[65 * 16:66 * 16].hex())
    inputs = [SOURCE, STARTUP, CODE, rb, TOOLS / 'mame.exe', TOOLS / 'chdman.exe',
              HERE / 'run.py', HERE / 'execute.lua', *glyph_inputs,
              ROOT / 'local/experiments/system-baseline/roms/maclc/350eacf0.rom']
    record = {'scope': 'Original glyph routine in a live Startup resource context; scheduled invocation after discovery',
              'run_directory': str(run), 'draw_calls': 128, 'inverse_writes': 1024,
              'inputs_sha256': {str(path): sha(path) for path in inputs},
              'capture_sha256': {path.name: sha(path) for path in run.glob('*.bin')}}
    (HERE / 'results.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS original glyph initialization with real QuickDraw and Resource Manager')


if __name__ == '__main__':
    main()
