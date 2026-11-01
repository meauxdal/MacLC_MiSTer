#!/usr/bin/env python3
"""Compose admitted non-keyboard dispatch and its live register tail."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-event-paths-live'
PARENT = HERE.parent / 'card-timer-delivery'
spec = importlib.util.spec_from_file_location('paths_timer_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index = 12; bridge_index <= 97;',
                'bridge_index = 12; bridge_index <= 105;')
    text = once(text, '    integer bridge_reply,', '''    integer event_commands = 0, event_controls = 0;
    always @(posedge clk_sys) begin
        if (bridge_active && dut.platform.card.card.keyboard_write)
            $fatal(1, "unexpected event keyboard pulse");
    end
    integer bridge_reply,''')
    marker = '            $display("REPLY %0d %0d", bridge_sequence, bridge_reply);'
    start = text.index('bridge_index = 12;')
    tail = once(text[start:], marker, '''            if (bridge_index > 20 && bridge_write && bridge_offset == 32) begin
                event_commands = event_commands + 1;
                if (bridge_value != 136) $fatal(1, "event command mismatch");
            end
            if (bridge_index == 68 || bridge_index == 105) begin
                if (!bridge_write || bridge_offset != 13 || bridge_value != 106)
                    $fatal(1, "event control mismatch");
                event_controls = event_controls + 1;
            end
''' + marker)
    text = text[:start] + tail
    text = once(text, '        bridge_active = 0;\n        wait(boundary);', '''        if (event_commands != 2 || event_controls != 2)
            $fatal(1, "event tail count mismatch");
        $display("EVENT commands=%0d controls=%0d", event_commands, event_controls);
        bridge_active = 0;
        wait(boundary);''')
    bench.write_text(text, encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge_path.write_text(once(bridge_path.read_text(), 'sequence <= 97', 'sequence <= 105'), encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), 'local/experiments/card-timer-delivery/bridge.lua',
                'local/experiments/card-event-paths-live/bridge.lua')
    host = once(host, 'off == 1 or off == 8 or off == 12 or off == 13 or off == 33',
                'off == 1 or off == 8 or off == 12 or off == 13 or off == 32 or off == 33')
    host = once(host, '        if offset == card + 28 and mask == 0xffff0000 then', '''        if offset == card + 32 and mask == 0xff000000 then
            bridge(true, 32, (data >> 24) & 255)
        elseif offset == card + 28 and mask == 0xffff0000 then''')
    marker = "    local zero_countdowns = ''"
    host = once(host, marker, '''    local event_type = assert(tonumber(os.getenv('IIE_PATH_EVENT')))
    assert(event_type == 1 or event_type == 2 or event_type == 11)
    for address = 0x174, 0x180, 4 do space:write_u32(address, 0) end
    space:write_u16(0x8d0, 0x8000)
    for address = 0x320000, 0x3202ff do space:write_u8(address, 0) end
    local tables = '; b@15d=80; w@(a5-874)=0; w@(a5-87a)=0'
    for slot = 0, 23 do
        tables = tables .. '; w@' .. string.format('%x', world - 0x1396 + slot * 2) .. '=0'
    end
    tables = tables .. '; w@' .. string.format('%x', world - 0x1394)
        .. '=' .. string.format('%x', 1 << ((event_type + 1) % 16))
    for index, slot in ipairs({20, 7, 0}) do
        local handler = 0x320000 + (index - 1) * 0x100
        tables = tables .. '; w@' .. string.format('%x', world - 0x1396 + slot * 2)
            .. '=' .. string.format('%x', 1 << event_type)
            .. '; d@' .. string.format('%x', world - 0x13ea + slot * 4)
            .. '=' .. string.format('%x', handler)
            .. '; d@' .. string.format('%x', world - 0x140a + slot * 4)
            .. '=' .. string.format('%x', 0x330000 + slot * 0x100)
        space:write_u16(handler + 0x1c, 0x70ff)
        space:write_u16(handler + 0x1e, 0x76ff)
        space:write_u16(handler + 0x20, 0x4e75)
        for _, phase in ipairs({4, 7}) do
            cpu.debug:bpset(handler + 0x1c, 'b@310027==' .. phase,
                'd@310100=d0; d@310104=d1; d@310108=d3; d@31010c=a0; '
                .. 'd@310110=a1; d@310114=a3; d@310118=a7; '
                .. 'save "' .. run .. '/handler-' .. phase .. '-' .. slot .. '.bin",310100,1c; g')
        end
    end
''' + marker)
    host = once(host, "        .. zero_countdowns .. '; ' .. callback(1))",
                "        .. zero_countdowns .. tables .. '; ' .. callback(1))")
    marker = "            .. 'save \"' .. run .. '/poll-' .. phase .. '-state.bin\",310000,10; ' .. continuation)"
    host = once(host, marker, '''            .. 'save "' .. run .. '/poll-' .. phase .. '-state.bin",310000,10; '
            .. ((phase == 4 or phase == 7) and 'g' or continuation))
        if phase == 4 or phase == 7 then
            cpu.debug:bpset(0x20250c, condition,
                'd@310080=d0; d@310084=a0; '
                .. 'save "' .. run .. '/event-' .. phase .. '-trap.bin",310080,8; '
                .. 'w@(a5-8e0)=' .. string.format('%x', event_type)
                .. '; d@(a5-8de)=ff41; d@(a5-8da)=12345678; d@(a5-8d6)=00020003; w@(a5-8d2)=0; '
                .. 'd0=0; pc=20250e; g')
            cpu.debug:bpset(0x2025f4, condition,
                'save "' .. run .. '/event-' .. phase .. '-pretail-world.bin",2fa6a0,5c49; '
                .. 'save "' .. run .. '/event-' .. phase .. '-handlers.bin",320000,300; g')
            cpu.debug:bpset(0x20284a, condition,
                'save "' .. run .. '/event-' .. phase .. '-world.bin",2fa6a0,5c49; '
                .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
                .. 'save "' .. run .. '/event-' .. phase .. '-state.bin",310000,10; ' .. continuation)
        end''')
    host = once(host, "    if os.getenv('IIE_BAD_TIMER') == '1' then", '''    if os.getenv('IIE_BAD_PATH') == '1' then
        cpu.debug:bpset(0x2025d8, 'b@310027==4 && d3==7',
            'save "' .. run .. '/event-fault-code.bin",200000,' .. (driver == 5 and 'a442' or '75d6') .. '; '
            .. 'd@310080=pc; pc=2025dc; d@310084=pc; '
            .. 'save "' .. run .. '/event-fault-pc.bin",310080,8; g')
    end
    if os.getenv('IIE_BAD_TIMER') == '1' then''')
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']
