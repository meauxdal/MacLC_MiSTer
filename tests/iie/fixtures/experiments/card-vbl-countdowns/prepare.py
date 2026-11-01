#!/usr/bin/env python3
"""Exercise nonzero device countdowns in the installed original VBL."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-vbl-countdowns'
PARENT = HERE.parent / 'card-timer-delivery'
spec = importlib.util.spec_from_file_location('countdown_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha
INITIAL = (0, 1, 2, 3, 4, 7, 0xffff, 0x8000)
RELOAD = (0, 0, 1, 2, 3, 7, 0xffff, 0x8000)


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    path = WORK / 'execute.lua'
    host = once(path.read_text(), 'local/experiments/card-timer-delivery/bridge.lua',
                'local/experiments/card-vbl-countdowns/bridge.lua')
    marker = "    local zero_countdowns = ''\n    for device = 0, 7 do\n        zero_countdowns = zero_countdowns .. '; w@' .. string.format('%x', world - 0x1366 + device * 2) .. '=0'\n    end"
    host = once(host, marker, '''    local zero_countdowns = ''
    local initial = {0, 1, 2, 3, 4, 7, 0xffff, 0x8000}
    local reload = {0, 0, 1, 2, 3, 7, 0xffff, 0x8000}
    for address = 0x320000, 0x3207ff do space:write_u8(address, 0) end
    for device = 0, 7 do
        local handler = 0x320000 + device * 0x100
        zero_countdowns = zero_countdowns
            .. '; w@' .. string.format('%x', world - 0x1366 + device * 2) .. '=' .. string.format('%x', initial[device + 1])
            .. '; w@' .. string.format('%x', world - 0x1336 + device * 2) .. '=' .. string.format('%x', reload[device + 1])
            .. '; d@' .. string.format('%x', world - 0x13ea + device * 4) .. '=' .. string.format('%x', handler)
            .. '; d@' .. string.format('%x', world - 0x140a + device * 4) .. '=' .. string.format('%x', 0x330000 + device * 0x100)
        space:write_u16(handler + 0x20, 0x74ff)
        space:write_u16(handler + 0x22, 0x76ff)
        space:write_u16(handler + 0x24, 0x4e75)
        for phase = 1, 7 do
            cpu.debug:bpset(handler + 0x20, 'b@310027==' .. phase,
                'd@310100=d1; d@310104=d2; d@310108=a0; d@31010c=a3; d@310110=a7; '
                .. 'save "' .. run .. '/device-' .. phase .. '-' .. device .. '.bin",310100,14; g')
        end
    end
    if os.getenv('IIE_BAD_COUNTDOWN') == '1' then
        cpu.debug:bpset(0x284926, 'b@310027==4 && d2==4',
            'save "' .. run .. '/countdown-fault-main.bin",280000,685c; '
            .. 'd@310100=pc; pc=28492a; d@310104=pc; '
            .. 'save "' .. run .. '/countdown-fault-pc.bin",310100,8; g')
    end''')
    marker = "        cpu.debug:bpset(0x290420 + (phase - 1) * 0x20, '1',\n            'save "
    host = once(host, marker, "        cpu.debug:bpset(0x290420 + (phase - 1) * 0x20, '1',\n"
                "            'save \"' .. run .. '/device-' .. phase .. '-stubs.bin\",320000,800; '\n"
                "            .. 'save ")
    path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']


if __name__ == '__main__':
    prepare()
