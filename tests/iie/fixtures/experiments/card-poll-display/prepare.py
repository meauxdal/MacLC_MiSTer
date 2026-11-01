#!/usr/bin/env python3
"""Exercise original polling and read-triggered display selection."""
import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-poll-display'
RENDER = HERE.parent / 'card-monitor-prompt-render'
spec = importlib.util.spec_from_file_location('poll_render_prepare', RENDER / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, text_oracle = parent.once, parent.sha, parent.text_oracle
ECHO, KEY, PROMPT, POST, MATCH = parent.ECHO, parent.KEY, parent.PROMPT, parent.POST, parent.MATCH
BASE, PARENT = parent.BASE, parent.PARENT


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    card = WORK / 'card_irq_candidate.sv'
    text = card.read_text()
    text = once(text, "wire display_switch = cpu_write && (cpu_address == 16'hC00F ||",
                "wire display_switch = (cpu_write || cpu_address >= 16'hC050) && (cpu_address == 16'hC00F ||")
    text = once(text, '&& cpu_running && !capture_valid && !boundary && !fault;',
                '&& cpu_running && !runtime_refresh && !capture_valid && !boundary && !fault;')
    start = text.index('    wire is_display =')
    end = text.index('    wire reset_vector =', start)
    text = text[:start] + '''    wire is_display = cpu_write &&
        ((cpu_address >= 16'h0400 && cpu_address < 16'h0800 && reset_mask[5]) ||
         (cpu_address >= 16'h0800 && cpu_address < 16'h0C00 && reset_mask[4]));
''' + text[end:]
    text = once(text, '(is_display && control[1:0] == 0)', 'is_display')
    text = once(text, "                    case (cpu_address)\n                        16'h0400:",
                "                    case (cpu_address & 16'hFC00)\n                        16'h0400:")
    text = once(text, "16'h0400: capture_status <= 8'h02", "16'h0400: capture_status <= 8'h42")
    text = once(text, "16'h0800: capture_status <= 8'h22", "16'h0800: capture_status <= 8'h62")
    if os.environ.get('IIE_POLL_CONTROL') == 'status':
        text = once(text, "16'h0400: capture_status <= 8'h42", "16'h0400: capture_status <= 8'h02")
    if os.environ.get('IIE_POLL_CONTROL') == 'pause':
        text = once(text, '(!runtime_paused || cpu_memory_wait)', '!runtime_paused')
    start = text.index('    assign boundary =')
    end = text.index('    assign master_valid[1]', start)
    text = text[:start] + "    reg test_live = 0, test_stop = 0;\n    assign boundary = test_stop || (!test_live && cpu_valid && cpu_sync && cpu_address == 16'hC27D && idle_reads == 260);\n" + text[end:]
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    start = text.index('    task render_checkpoint;')
    end = text.index('    reg [7:0] input_buffer', start)
    text = text[:start] + '''    reg [1023:0] live_page_path;
    reg page_saved = 0;
    integer page_file;
    always @(negedge clk_sys) begin
        if (boundary && !page_saved) begin
            check_idle();
            page_file = $fopen(live_page_path, "wb");
            if (page_file == 0) $fatal(1, "live page open failed");
            for (integer offset = 0; offset < 1024; offset = offset + 1)
                $fwrite(page_file, "%c", backing('h400 + offset));
            $fclose(page_file);
            page_saved = 1;
            $display("POLL_IDLE CPU=%0d writes=%0d captures=%0d", cpu_completed, stores, capture_count);
            $fflush();
        end
    end
''' + text[end:]
    start = text.index('                if (bridge_width == 0) begin')
    end = text.index('                transact(bridge_write, bridge_width == 16, bridge_offset, bridge_value, 0);', start)
    text = text[:start] + text[end:]
    text = once(text, '                end\n                $display("REPLY', '                $display("REPLY')
    text = once(text, '                transact(bridge_write, bridge_width == 16, bridge_offset, bridge_value, 0);',
                '''                if (!bridge_write && bridge_offset == 1 && !capture_valid &&
                    !dut.platform.card.card.runtime_paused)
                    repeat (1024) @(negedge clk_sys);
                transact(bridge_write, bridge_width == 16, bridge_offset, bridge_value, 0);''')
    text = text.replace('bridge_index > 2048', 'bridge_index > 16384')
    text = once(text, 'ticks > 2000000', 'ticks > 8000000')
    start = text.index('        while (capture_address !=')
    end = text.index('        bridge_active = 1;', start)
    text = text[:start] + text[end:]
    start = text.index('        if (!render_started ||')
    end = text.index('        stop_competitors = 1;', start)
    text = text[:start] + '''        if (!page_saved || !boundary || capture_valid) $fatal(1, "poll endpoint missing");
        force dut.platform.card.card.pace_due = 0;
        dut.platform.card.card.test_live = 1;
        pause_pending(0);
        pause_pending(1);
        transact(1, 0, 32, 128, 0);
        wait(!dut.platform.card.card.cpu_memory_wait && dut.platform.card.card.drained);
        dut.platform.card.card.test_stop = 1;
        transact(1, 0, 32, 136, 0);
        transact(1, 0, 12, 0, 0);
        $display("POLL_ACCOUNT transactions=%0d captures=%0d", transaction_count, capture_count);
''' + text[end:]
    text = once(text, '    reg [1023:0] live_page_path;', (HERE / 'pause.sv').read_text() + '\n    reg [1023:0] live_page_path;')
    text = once(text, 'capture_count != switch_services + 68 || capture_valid ||', 'capture_valid ||')
    text = once(text, 'PASS prompt-render fast=', 'PASS poll-display fast=')
    bench.write_text(text, encoding='ascii')
    host = WORK / 'host.lua'
    text = host.read_text()
    text = text.replace('sequence <= 2048', 'sequence <= 16384')
    start = text.index('            if return_writes == 30 and')
    end = text.index('            local result = bridge(', start)
    text = text[:start] + text[end:]
    text = once(text, '            record(false, count * 8, off, result)', '''            if off == 1 and result == 0 then
                local idle = io.open(run .. '/live-page.bin', 'rb')
                if idle then idle:close(); space:write_u8(0x310028, 1) end
            end
            record(false, count * 8, off, result)''')
    text = once(text, '            local result = bridge(false, count * 8, off, 0)',
                '''            if space:read_u8(0x310028) == 2 then return data & ~mask end
            local result = bridge(false, count * 8, off, 0)''')
    text = once(text, "        cpu.debug:bpset(base + 0x281c, 'temp5==2',", "        cpu.debug:bpset(base + 0x2836, 'b@310028==1',")
    start = text.index('            .. \'printf "KEY_BOUNDARY')
    end = text.index("        cpu.state['A4']", start)
    text = text[:start] + '''            .. 'd@310010=pc; d@310014=a7; save "' .. run .. '/render-state.bin",310010,8; '
            .. 'save "' .. run .. '/render-world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/render-code.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'save "' .. run .. '/render-main.bin",280000,685c; '
            .. 'save "' .. run .. '/render-frame.bin",fffc0,' .. string.format('%x', frame_size + 128) .. '; '
            .. 'b@310028=2; trace off,:maincpu; quit')
''' + text[end:]
    text = once(text, "        cpu.state['PC'].value = base + 0x7ae", '''        overlay(assert(os.getenv('IIE_RENDER_GLYPH')), world - 0x2412)
        overlay(assert(os.getenv('IIE_MAIN_CODE')), 0x280000)
        space:write_u8(0x310028, 0)
        space:write_u32(0x3efff8, base + 0x7ae)
        cpu.state['A7'].value = 0x3efff8
        cpu.state['PC'].value = 0x284300''')
    host.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'run.py', HERE / 'checks.py', HERE / 'pause.sv']
