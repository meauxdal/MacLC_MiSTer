#!/usr/bin/env python3
"""Bind original VBL installation and periodic admission to live PDS."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-vbl-admission'
PARENT = ROOT / 'fixtures/experiments/card-reload-service4'
spec = importlib.util.spec_from_file_location('vbl_service4_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index = 12; bridge_index <= 20;',
                'bridge_index = 12; bridge_index <= 83;')
    marker = '            $fflush();\n        end\n        bridge_active = 0;\n        wait(boundary);'
    text = once(text, marker, '            $fflush();\n'
                '            if (bridge_index == 20) begin\n'
                '                wait(boundary);\n'
                '                transact(1, 0, 13, 234, 0);\n'
                "                transact(1, 1, 28, 'hBEEF, 0);\n"
                '            end\n'
                '        end\n        bridge_active = 0;\n        wait(boundary);')
    text = once(text, 'PASS reload service4 fast=', 'PASS VBL admission fast=')
    bench.write_text(text, encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge = once(bridge_path.read_text(), 'sequence <= 20', 'sequence <= 83')
    bridge = once(bridge, 'offset == 4 and 16 or 8', '(offset == 4 or offset == 28) and 16 or 8')
    bridge_path.write_text(bridge, encoding='ascii')

    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), 'local/experiments/card-reload-service4/bridge.lua',
                'local/experiments/card-vbl-admission/bridge.lua')
    host = once(host, 'off == 1 or off == 12 or off == 13 or off == 33',
                'off == 1 or off == 8 or off == 12 or off == 13 or off == 33')
    host = once(host, '(count == 2 and off == 4)', '(count == 2 and (off == 4 or off == 28))')
    host = once(host, '        if offset == card + 12 and mask == 0x00ff0000 then', '''        if offset == card + 28 and mask == 0xffff0000 then
            bridge(true, 28, (data >> 16) & 0xffff)
        elseif offset == card + 12 and mask == 0x00ff0000 then''')
    host = once(host, "cpu.debug:bpset(0x20281c, 'b@310024==2',",
                "cpu.debug:bpset(0x20281c, 'b@310024==2 && b@310026==0',")
    marker = "        .. 'save \"' .. run .. '/final-state.bin\",310000,10; trace off,:maincpu; quit')"
    host = once(host, marker, '''        .. 'save "' .. run .. '/final-state.bin",310000,10; '
        .. 'b@310026=1; d@3efffc=290400; a7=3efffc; pc=2842bc; g')
    cpu.debug:bpset(0x2842c2, 'b@310026==1', 'pc=28485a; g')
    cpu.debug:bpset(0x284870, 'b@310026==1',
        'd@310080=a0; d@310084=d0; save "' .. run .. '/install-vbl.bin",310080,8; '
        .. 'd0=0; pc=284872; g')
    cpu.debug:bpset(0x28488a, 'b@310026==1',
        'd@310080=a0; d@310084=d0; save "' .. run .. '/install-timer.bin",310080,8; '
        .. 'd0=0; pc=28488c; g')
    local function callback(phase)
        return 'b@310027=' .. phase .. '; d@3e0000='
            .. string.format('%x', 0x290420 + (phase - 1) * 0x20)
            .. '; d3=11223303; d4=11223304; d5=11223305; d6=11223306; d7=11223307'
            .. '; a2=22334402; a3=22334403; a4=22334404; a5=33445500; a6=33445566'
            .. '; a0=2ff75a; a7=3e0000; pc=d@2ff760; g'
    end
    local zero_countdowns = ''
    for device = 0, 7 do
        zero_countdowns = zero_countdowns .. '; w@' .. string.format('%x', world - 0x1366 + device * 2) .. '=0'
    end
    cpu.debug:bpset(0x290400, '1',
        'save "' .. run .. '/install-world.bin",2fa6a0,5c49; '
        .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
        .. 'save "' .. run .. '/install-state.bin",310000,10'
        .. zero_countdowns .. '; ' .. callback(1))
    for phase = 1, 7 do
        local prefix = run .. '/vbl-' .. phase .. '-'
        local condition = 'b@310027==' .. phase
        cpu.debug:bpset(0x2848da, condition,
            'd@310080=a0; d@310084=d0; save "' .. run .. '/prime-' .. phase .. '.bin",310080,8; '
            .. 'd0=0; pc=2848dc; g')
        cpu.debug:bpset(0x290420 + (phase - 1) * 0x20, '1',
            'save "' .. prefix .. 'world.bin",2fa6a0,5c49; '
            .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
            .. 'save "' .. prefix .. 'state.bin",310000,10; '
            .. 'd@310040=d3; d@310044=d4; d@310048=d5; d@31004c=d6; d@310050=d7; '
            .. 'd@310054=a2; d@310058=a3; d@31005c=a4; d@310060=a5; '
            .. 'save "' .. prefix .. 'registers.bin",310040,24; '
            .. 'a5=300000; a7=3f0000; pc=20281c; g')
        local continuation = phase < 7 and callback(phase + 1)
            or 'save "' .. run .. '/scheduler-world.bin",2fa6a0,5c49; '
                .. 'save "' .. run .. '/scheduler-frame.bin",fffc0,' .. string.format('%x', frame_size + 128)
                .. '; save "' .. run .. '/scheduler-code.bin",200000,' .. (driver == 5 and 'a442' or '75d6')
                .. '; save "' .. run .. '/scheduler-main.bin",280000,685c; '
                .. 'save "' .. run .. '/scheduler-converted.bin",370000,4080; trace off,:maincpu; quit'
        cpu.debug:bpset((phase == 4 or phase == 7) and 0x202846 or 0x202832, condition,
            'save "' .. run .. '/poll-' .. phase .. '-world.bin",2fa6a0,5c49; '
            .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
            .. 'save "' .. run .. '/poll-' .. phase .. '-state.bin",310000,10; ' .. continuation)
    end
    if os.getenv('IIE_BAD_VBL') == '1' then
        cpu.debug:bpset(0x2848bc, 'b@310027==4', 'pc=2848c0; g')
    end''')
    host = once(host, '    space:write_u8(0x310024, 0)',
                '    space:write_u8(0x310024, 0)\n    space:write_u8(0x310026, 0)\n    space:write_u8(0x310027, 0)')
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']


if __name__ == '__main__':
    prepare()
