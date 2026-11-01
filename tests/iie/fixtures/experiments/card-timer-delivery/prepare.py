#!/usr/bin/env python3
"""Deliver the installed Time Manager callback after each original VBL."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-timer-delivery'
PARENT = ROOT / 'fixtures/experiments/card-vbl-admission'
spec = importlib.util.spec_from_file_location('timer_vbl_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index = 12; bridge_index <= 83;',
                'bridge_index = 12; bridge_index <= 97;')
    bench.write_text(text, encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge = once(bridge_path.read_text(), 'sequence <= 83', 'sequence <= 97')
    bridge_path.write_text(bridge, encoding='ascii')

    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), 'local/experiments/card-vbl-admission/bridge.lua',
                'local/experiments/card-timer-delivery/bridge.lua')
    host = once(host, "    space:write_u8(0x310027, 0)",
                "    space:write_u8(0x310027, 0)\n    space:write_u8(0x310028, 0)\n    space:write_u32(0x31008c, 0)")
    marker = "            .. 'd0=0; pc=2848dc; g')"
    host = once(host, marker, '''            .. 'save "' .. run .. '/prime-' .. phase .. '-pending.bin",310028,1; '
            .. 'd@31008c=a0; b@310028=1; d0=0; pc=2848dc; g')''')
    marker = "            .. 'a5=300000; a7=3f0000; pc=20281c; g')"
    host = once(host, marker, '''            .. 'd@310080=d@31008c; d@310084=d@(d@31008c+6); d@310088=b@310028; '
            .. 'save "' .. run .. '/timer-' .. phase .. '-delivery.bin",310080,c; '
            .. 'b@310028=0; d@3d0000=' .. string.format('%x', 0x290600 + (phase - 1) * 0x20)
            .. '; a1=d@31008c; a5=55667700; a7=3d0000; pc=d@(a1+6); g')
        cpu.debug:bpset(0x290600 + (phase - 1) * 0x20, '1',
            'save "' .. run .. '/timer-' .. phase .. '-world.bin",2fa6a0,5c49; '
            .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
            .. 'save "' .. run .. '/timer-' .. phase .. '-state.bin",310000,10; '
            .. 'd@310040=d3; d@310044=d4; d@310048=d5; d@31004c=d6; d@310050=d7; '
            .. 'd@310054=a2; d@310058=a3; d@31005c=a4; d@310060=a5; '
            .. 'save "' .. run .. '/timer-' .. phase .. '-registers.bin",310040,24; '
            .. 'd@310080=a0; d@310084=a1; '
            .. 'save "' .. run .. '/timer-' .. phase .. '-addresses.bin",310080,8; '
            .. 'save "' .. run .. '/timer-' .. phase .. '-pending.bin",310028,1; '
            .. 'a5=300000; a7=3f0000; pc=20281c; g')''')
    marker = "    if os.getenv('IIE_BAD_VBL') == '1' then"
    host = once(host, marker, '''    if os.getenv('IIE_BAD_TIMER') == '1' then
        cpu.debug:bpset(0x2848a4, 'b@310027==4',
            'save "' .. run .. '/timer-fault-main.bin",280000,685c; '
            .. 'd@310080=pc; pc=2848aa; d@310084=pc; '
            .. 'save "' .. run .. '/timer-fault-pc.bin",310080,8; g')
    end
''' + marker)
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']


if __name__ == '__main__':
    prepare()
