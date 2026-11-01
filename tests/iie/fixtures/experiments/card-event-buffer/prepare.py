#!/usr/bin/env python3
"""Exercise original keyboard queue wraparound over live PDS."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-event-buffer'
PARENT = HERE.parent / 'card-event-live'
spec = importlib.util.spec_from_file_location('buffer_event_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    bench.write_text(once(bench.read_text(), 'bridge_index <= 99;', 'bridge_index <= 111;'), encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge_path.write_text(once(bridge_path.read_text(), 'sequence <= 99', 'sequence <= 111'), encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), 'local/experiments/card-event-live/bridge.lua',
                'local/experiments/card-event-buffer/bridge.lua')
    host = once(host, 'off == 1 or off == 8 or off == 12', 'off == 1 or off == 8 or off == 9 or off == 12')
    host = once(host, 'off == 13 or off == 33', 'off == 13 or off == 32 or off == 33')
    host = once(host, '        if offset == card + 24 and mask == 0xff000000 then', '''        if offset == card + 32 and mask == 0xff000000 then
            bridge(true, 32, (data >> 24) & 255)
        elseif offset == card + 24 and mask == 0xff000000 then''')
    setup = '; w@(a5-87a)=1; w@(a5-8ea)=1f; w@(a5-8ec)=1f'
    for index in range(32):
        setup += f'; d@{0x300000 - 0x96c + index * 4:x}={(index + 1) * 0x10000 + 0x1200 + index:x}'
    host = once(host, '; w@(a5-87a)=0;', setup + '; d@174=1; d@178=0; d@17c=0; d@180=0;')
    marker = "            cpu.debug:bpset(0x20284a, condition,"
    host = once(host, marker, '''            cpu.debug:bpset(0x2025f4, condition,
                'save "' .. run .. '/queued-' .. phase .. '-world.bin",2fa6a0,5c49; g')
''' + marker)
    host = once(host, "    if os.getenv('IIE_BAD_EVENT') == '1' then", "    if os.getenv('IIE_BAD_QUEUE') == '1' then")
    host = once(host, "cpu.debug:bpset(0x202730, 'b@310027==4',", "cpu.debug:bpset(0x20271a, 'b@310027==4',")
    host = once(host, 'd@310080=pc; pc=202734;', 'd@310080=pc; pc=20271e;')
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']
