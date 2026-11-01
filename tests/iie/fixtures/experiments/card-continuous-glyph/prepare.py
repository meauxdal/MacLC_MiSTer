#!/usr/bin/env python3
"""Join live QuickDraw glyph construction to the polling/display candidate."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-continuous-glyph'
POLL = HERE.parent / 'card-poll-display'
spec = importlib.util.spec_from_file_location('continuous_poll_prepare', POLL / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha
RENDER, ECHO, KEY, PROMPT, POST, MATCH = parent.RENDER, parent.ECHO, parent.KEY, parent.PROMPT, parent.POST, parent.MATCH
BASE, PARENT = parent.BASE, parent.PARENT


def text_oracle():
    oracle, inputs = parent.text_oracle()
    bitmap = bytearray(oracle['glyph_state']())
    bitmap[32 * 16:33 * 16] = bytes(16)
    bitmap[160 * 16:161 * 16] = bytes.fromhex('01fc') * 8
    oracle['glyph_state'] = lambda: bytes(bitmap)
    return oracle, inputs


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    tools = Path('C:/Users/Elle/Downloads/mame0289b_x64')
    original = ROOT / 'local/hardfiles/Apple-II_100MB.hda'
    startup = ROOT / 'local/experiments/firmware-memory/v221/Apple IIe Card 2.2.1.image'
    rb = ROOT / 'local/experiments/system-baseline/rb/rb-cli.exe'
    disk = WORK / 'autostart.hda'
    shutil.copyfile(original, disk)
    subprocess.run([str(rb), 'cp', str(startup), '/IIe Startup', str(disk),
                    '/System 7.1.2/Startup Items/IIe Startup'], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    chd = WORK / 'autostart.chd'
    subprocess.run([str(tools / 'chdman.exe'), 'createhd', '-f', '-i', str(disk), '-o', str(chd),
                    '-c', 'none', '-chs', '6403,1,32', '-ss', '512'], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    host = WORK / 'host.lua'
    text = host.read_text()
    start = text.index('emu.register_frame_done(function()')
    body = text.index('        local file =', start)
    end = text.index('    elseif frames > 3000 then', body)
    text = text[:start] + text[body:end]
    text = once(text, 'local base, world, card = 0x200000, 0x300000, 0xe00000', '''local live = assert(_G.iie_live)
local base, world, card = live.base, live.world, 0xe00000
local machine = manager.machine
local cpu = machine.devices[':maincpu']
local space = cpu.spaces['program']
local relocate, map_command = live.relocate, live.map_command
local function bp(address, condition, action)
    action = map_command(action)
    if action:find('quit', 1, true) then action = action:gsub('quit', 'b@310000=4; quit') end
    cpu.debug:bpset(address, map_command(condition), action)
end''')
    text = text.replace('cpu.debug:bpset(', 'bp(')
    text = once(text, 'local taps = {}', 'local taps = {}\n_G.iie_live_taps = taps')
    text = once(text, '    bp(address, map_command(condition), action)',
                '    cpu.debug:bpset(address, map_command(condition), action)')
    start = text.index('        for i = world - 0x5960, world + 0x2e8')
    end = text.index("        file = assert(io.open(assert(os.getenv('IIE_SWITCH_WORLD'))", start)
    text = text[:start] + text[end:]
    text = text.replace('0x100000', 'live.frame')
    import re
    text = re.sub(r'\b0x(?:310[0-9a-f]{3}|360[0-9a-f]{3}|3ef[0-9a-f]{3})\b',
                  lambda match: 'relocate(' + match[0] + ')', text)
    text = once(text, "        overlay(assert(os.getenv('IIE_RENDER_GLYPH')), world - 0x2412)\n", '')
    text = once(text, "        overlay(assert(os.getenv('IIE_MAIN_CODE')), 0x280000)\n", '')
    text = once(text, "        cpu.state['PC'].value = 0x284300", "        cpu.state['PC'].value = base + 0x4a")
    text = once(text, "        cpu.state['A7'].value = relocate(0x3efff8)",
                "        cpu.state['A7'].value = relocate(0x3efff4)")
    text = once(text, "        space:write_u8(relocate(0x310028), 0)", '''        space:write_u8(relocate(0x310028), 0)
        space:write_u32(relocate(0x3efff4), live.main + 0x4300)
        space:write_u32(relocate(0x3efff8), base + 0x7ae)
        space:write_u32(relocate(0x3efffc), base + 0x2c4)
        _G.iie_finish = function()
            local state = assert(io.open(run .. '/state.txt', 'w'))
            state:write(string.format('services=%d returns=%d transactions=%d pc=%x sp=%x\\n',
                service_acks, return_writes, sequence, cpu.state['PC'].value, cpu.state['A7'].value))
            state:close()
            bus:close()
            registers:close()
        end''')
    host.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'run.py', HERE / 'checks.py',
        HERE / 'bootstrap.lua', original, startup, rb, tools / 'chdman.exe']
