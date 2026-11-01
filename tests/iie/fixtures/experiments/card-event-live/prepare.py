#!/usr/bin/env python3
"""Continue admitted polling through original event writes to live PDS."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-event-live'
PARENT = HERE.parent / 'card-timer-delivery'
spec = importlib.util.spec_from_file_location('event_timer_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index = 12; bridge_index <= 97;',
                'bridge_index = 12; bridge_index <= 99;')
    text = once(text, '    integer bridge_reply,', '''    integer event_writes = 0, event_pulses = 0;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.keyboard_write) begin
            event_pulses <= event_pulses + 1;
            if (event_pulses >= 2 || dut.platform.card.card.sidefx_wdata[7:0] !== 8'h41 + event_pulses)
                $fatal(1, "event keyboard pulse mismatch");
        end
    end
    integer bridge_reply,''')
    marker = '            $display("REPLY %0d %0d", bridge_sequence, bridge_reply);'
    assert text.count(marker) == 2
    start = text.index('bridge_index = 12;')
    tail = once(text[start:], marker, '''            if (bridge_write && bridge_offset == 24) begin
                event_writes = event_writes + 1;
                if (event_writes > 2 || event_pulses != event_writes || bridge_value != 64 + event_writes ||
                    dut.platform.card.card.keyboard !== bridge_value[7:0])
                    $fatal(1, "event keyboard latch mismatch");
                $display("EVENT write=%0d keyboard=%h", event_writes, dut.platform.card.card.keyboard);
            end
''' + marker)
    text = text[:start] + tail
    text = once(text, '        bridge_active = 0;\n        wait(boundary);',
                '''        if (event_writes != 2 || event_pulses != 2 || dut.platform.card.card.keyboard !== 8'h42)
            $fatal(1, "event write count mismatch");
        bridge_active = 0;
        wait(boundary);''')
    bench.write_text(text, encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge_path.write_text(once(bridge_path.read_text(), 'sequence <= 97', 'sequence <= 99'), encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), 'local/experiments/card-timer-delivery/bridge.lua',
                'local/experiments/card-event-live/bridge.lua')
    host = once(host, '        if offset == card + 28 and mask == 0xffff0000 then',
                '''        if offset == card + 24 and mask == 0xff000000 then
            bridge(true, 24, (data >> 24) & 255)
        elseif offset == card + 28 and mask == 0xffff0000 then''')
    host = once(host, "        .. zero_countdowns .. '; ' .. callback(1))",
                "        .. zero_countdowns .. '; b@15d=80; w@(a5-874)=0; w@(a5-87a)=0; ' .. callback(1))")
    marker = "            .. 'save \"' .. run .. '/poll-' .. phase .. '-state.bin\",310000,10; ' .. continuation)"
    host = once(host, marker, '''            .. 'save "' .. run .. '/poll-' .. phase .. '-state.bin",310000,10; '
            .. ((phase == 4 or phase == 7) and 'g' or continuation))
        if phase == 4 or phase == 7 then
            cpu.debug:bpset(0x20250c, condition,
                'd@310080=d0; d@310084=a0; '
                .. 'save "' .. run .. '/event-' .. phase .. '-trap.bin",310080,8; '
                .. 'w@(a5-8e0)=' .. (phase == 4 and '3' or '5')
                .. '; d@(a5-8de)=' .. (phase == 4 and 'ff41' or 'ff42')
                .. '; d@(a5-8da)=12345678; d@(a5-8d6)=00020003; w@(a5-8d2)=0; '
                .. 'd0=0; pc=20250e; g')
            cpu.debug:bpset(0x20284a, condition,
                'save "' .. run .. '/event-' .. phase .. '-world.bin",2fa6a0,5c49; '
                .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
                .. 'save "' .. run .. '/event-' .. phase .. '-state.bin",310000,10; ' .. continuation)
        end''')
    host = once(host, "    if os.getenv('IIE_BAD_TIMER') == '1' then", '''    if os.getenv('IIE_BAD_EVENT') == '1' then
        cpu.debug:bpset(0x202730, 'b@310027==4',
            'save "' .. run .. '/event-fault-code.bin",200000,' .. (driver == 5 and 'a442' or '75d6') .. '; '
            .. 'd@310080=pc; pc=202734; d@310084=pc; '
            .. 'save "' .. run .. '/event-fault-pc.bin",310080,8; g')
    end
    if os.getenv('IIE_BAD_TIMER') == '1' then''')
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']
