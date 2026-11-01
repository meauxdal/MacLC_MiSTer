#!/usr/bin/env python3
"""Run the original PAGE2 mode change against a held native-memory card."""
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-page2'
PARENT = ROOT / 'fixtures/experiments/card-service4-render'
spec = importlib.util.spec_from_file_location('render_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, snapshot_inputs = parent.once, parent.sha, parent.snapshot_inputs
FIRST_ACK, LAST_ACK = 1048, 1055


def prepare():
    pins_path = PARENT / 'results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    assert sha(PARENT / 'prepare.py') == pins[str(PARENT / 'prepare.py')]
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    card_path = WORK / 'card_irq_candidate.sv'
    card = card_path.read_text()
    card = once(card, 'parameter FIXED_CX = 0,', 'parameter IGNORE_RUNTIME_PAUSE = 0, parameter FIXED_CX = 0,')
    card = once(card, 'reg cpu_running, start_pending, armed, report_mode;',
                'reg cpu_running, start_pending, armed, report_mode;\n    reg runtime_paused;')
    card = once(card, 'wire runnable = cpu_valid &&', 'wire runnable = (!runtime_paused || cpu_memory_wait) && cpu_valid &&')
    card = re.sub(r'(?m)^( *)armed <= 0;$', r'\1armed <= 0;\n\1runtime_paused <= 0;', card)
    card = once(card, "                end else if (!sidefx_word && (sidefx_wdata[7:0] & 8'hDF) == 8'h88) begin", """                end else if (!IGNORE_RUNTIME_PAUSE && !sidefx_word && sidefx_wdata[7:0] == 8'h80 &&
                             armed && reset_mask != 8'hFC) begin
                    runtime_paused <= 1;
                end else if (!sidefx_word && (sidefx_wdata[7:0] & 8'hDF) == 8'h88) begin""")
    card = once(card, '                        armed <= 1;', '                        armed <= 1;\n                        runtime_paused <= 0;')
    card_path.write_text(card, encoding='ascii')
    bench = sources[0]
    text = once(bench.read_text(), 'parameter FAST = 0', 'parameter FAST = 0, BAD_PAUSE = 0')
    text = once(text, '    defparam dut.platform.card.card.PACE_FAST = FAST;',
                '    defparam dut.platform.card.card.PACE_FAST = FAST;\n    defparam dut.platform.card.card.IGNORE_RUNTIME_PAUSE = BAD_PAUSE;\n    integer pause_cycles, pause_captures;')
    text = once(text, 'bridge_index <= 7;', f'bridge_index <= {FIRST_ACK};')
    text = once(text, 'bridge_index = 8; bridge_index <= 16;', f'bridge_index = {FIRST_ACK + 1}; bridge_index <= {LAST_ACK};')
    marker = '        if (!$value$plusargs("mask=%d", mask_seed)) mask_seed = 252;'
    text = once(text, marker, """        if (dut.platform.card.card.cpu_memory_wait) $fatal(1, "fixture while CPU memory outstanding");
        for (i = 0; i < 1024; i = i + 1) begin
            expected['h800 + i] = 8'(i * 37 + (i / 16) * 11 + 61);
            if (i % 2 == 0) memory[('h800 + i) / 2][7:0] = expected['h800 + i];
            else memory[('h800 + i) / 2][15:8] = expected['h800 + i];
        end
        pause_cycles = int'(cpu_completed);
        pause_captures = int'(capture_count);
""" + marker)
    marker = '            $display("REPLY %0d %0d", bridge_sequence, bridge_reply);'
    assert text.count(marker) == 2
    insertion = """            if (bridge_index >= 4 && bridge_index <= 13 &&
                (!dut.platform.card.card.runtime_paused || cpu_completed != 32'(pause_cycles) ||
                 capture_count != 32'(pause_captures) || !capture_valid || capture_data != 1 ||
                 capture_address != 16'hC07D || dut.platform.card.card.reset_pending))
                $fatal(1, "runtime pause lost held execution");
            if (bridge_index == 14 && dut.platform.card.card.runtime_paused)
                $fatal(1, "runtime resume remained paused");
"""
    text = text.replace(marker, insertion + marker, 1)
    text = once(text, 'transact(0, 0, 33, (mask_seed & 3) | 32, 0);',
                'transact(0, 0, 33, (mask_seed & 3) | 48, 0);')
    text = once(text, 'PASS service4 rendered fast=', 'PASS page2 rendered fast=')
    bench.write_text(text, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), "dofile('fixtures/experiments/card-service4-render/bridge.lua')",
                "dofile('fixtures/experiments/card-display-page2/bridge.lua')")
    host = once(host, '        space:write_u16(world - 0x972, 0)', '        space:write_u16(world - 0x972, 2)')
    host = once(host, 'space:write_u16(world - 0x97c, 0x5a5a)', 'space:write_u16(world - 0x97c, 0)')
    host = once(host, '        space:write_u32(world - 0x1236, card)', """        local stride = frame_size // 480
        for y = 48, 431 do
            local start = 0x100000 + y * stride + (stride == 320 and 20 or 4)
            for x = 0, (stride == 320 and 280 or 70) - 1 do space:write_u8(start + x, 0xff) end
        end
        space:write_u32(world - 0x1236, card)""")
    host = once(host, "cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')",
                "cpu.debug:bpset(base + 0x2d4, '1', 'a7=3efffc; pc=2007ae; g')")
    host = once(host, "        space:write_u32(0x3efffc, base + 0x2c4)\n        cpu.state['A7'].value = 0x3efffc\n        cpu.state['PC'].value = base + 0x7ae",
                "        space:write_u32(0x3efffc, base + 0x281c)\n        cpu.state['PC'].value = base + 0x2c4")
    start = host.index('            if offset - card == 0x20 and mask == 0x00ff0000 then')
    end = host.index('            acks = acks + 1', start)
    host = host[:start] + """            local first, count = nil, 0
            for lane = 0, 3 do
                if ((mask >> ((3 - lane) * 8)) & 0xff) ~= 0 then
                    first = first or lane
                    count = count + 1
                end
            end
            local off = offset - card + first
            local value = (data >> ((4 - first - count) * 8)) & ((1 << (count * 8)) - 1)
            if off ~= 12 then
                assert(off == 13 or off == 28 or off == 32 or off == 33, 'Unexpected write register')
                bridge(true, count * 8, off, value)
                bus:write(string.format('[true,%d,%d,%d]\\n', count * 8, off, value))
                return
            end
            assert(count == 1 and value == 0, 'Unexpected ACK')
""" + host[end:]
    host = once(host, '            if acks == 2 then', '            if acks >= 1 then')
    host = once(host, "snapshot('frame.bin',", "snapshot(acks == 1 and 'mode-frame.bin' or 'frame.bin',")
    host = once(host, "snapshot('preack-world.bin',", "snapshot(acks == 1 and 'mode-world.bin' or 'preack-world.bin',")
    host = once(host, "snapshot('code-after.bin',", "snapshot(acks == 1 and 'mode-code.bin' or 'code-after.bin',")
    host = once(host, "            .. 'printf \"RENDER_BOUNDARY pc=%08X sp=%08X\",pc,a7; trace off,:maincpu; quit')",
                "            .. 'd@330000=pc; d@330004=a7; save \"' .. run .. '/state.bin\",330000,8; trace off,:maincpu; quit')")
    start = host.index('    elseif frames == 3001 then')
    host = host[:start] + '    end\nend)\n'
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'bridge.lua', PARENT / 'prepare.py', pins_path]
