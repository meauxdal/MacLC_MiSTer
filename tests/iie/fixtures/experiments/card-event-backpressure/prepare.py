#!/usr/bin/env python3
"""Keep the keyboard busy while original events meet empty or full queues."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-event-backpressure'
PARENT = HERE.parent / 'card-event-buffer'
spec = importlib.util.spec_from_file_location('busy_buffer_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index <= 111;', 'bridge_index <= 109;')
    text = once(text, "event_pulses >= 2 || dut.platform.card.card.sidefx_wdata[7:0] !== 8'h41 + event_pulses",
                "event_pulses != 0 || dut.platform.card.card.sidefx_wdata[7:0] !== 8'hD5")
    start = text.index('            if (bridge_write && bridge_offset == 24) begin')
    end = text.index('            $display("REPLY', start)
    text = text[:start] + '''            if (bridge_write && bridge_offset == 24)
                $fatal(1, "busy keyboard received event write");
''' + text[end:]
    text = once(text, 'event_writes != 2 || event_pulses != 2 || dut.platform.card.card.keyboard !== 8\'h42',
                'event_writes != 0 || event_pulses != 1 || dut.platform.card.card.keyboard !== 8\'hD5')
    text = once(text, "                transact(1, 1, 28, 'hBEEF, 0);",
                "                transact(1, 1, 28, 'hBEEF, 0);\n                transact(1, 0, 24, 213, 0);")
    text = once(text, '        bridge_active = 0;\n        wait(boundary);\n        if (dut.platform.card.card.processor',
                '        $display("BUSY keyboard=d5 pulses=%0d", event_pulses);\n        bridge_active = 0;\n        wait(boundary);\n        if (dut.platform.card.card.processor')
    bench.write_text(text, encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge_path.write_text(once(bridge_path.read_text(), 'sequence <= 111', 'sequence <= 109'), encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), 'local/experiments/card-event-buffer/bridge.lua',
                'local/experiments/card-event-backpressure/bridge.lua')
    setup = '''    local full_queue = os.getenv('IIE_FULL_QUEUE') == '1'
'''
    host = once(host, '    local zero_countdowns =', setup + '    local zero_countdowns =')
    marker = "        .. zero_countdowns .. '; b@15d=80;"
    assert marker in host
    for index in range(32):
        old = f'; d@{0x300000 - 0x96c + index * 4:x}={(index + 1) * 0x10000 + 0x1200 + index:x}'
        host = once(host, old, old + ("' .. (full_queue and '; b@%x=80' or '') .. '" % (0x300000 - 0x96c + index * 4)))
    start = host.index("    if os.getenv('IIE_BAD_QUEUE') == '1' then")
    end = host.index("    if os.getenv('IIE_BAD_TIMER')", start)
    host = host[:start] + '''    if os.getenv('IIE_BAD_BUSY') == '1' then
        local fault_pc = full_queue and 0x202718 or 0x202486
        local resume_pc = full_queue and 0x20271a or 0x202488
        local condition = full_queue and 'b@310027==4'
            or 'b@310027==4 && (b@(a5-96c+w@(a5-8ec)*4)&80)!=0'
        cpu.debug:bpset(fault_pc, condition,
            'save "' .. run .. '/busy-fault-world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/busy-fault-code.bin",200000,' .. (driver == 5 and 'a442' or '75d6') .. '; '
            .. 'd@310080=pc; pc=' .. string.format('%x', resume_pc) .. '; d@310084=pc; '
            .. 'save "' .. run .. '/busy-fault-pc.bin",310080,8; g')
    end
''' + host[end:]
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']
