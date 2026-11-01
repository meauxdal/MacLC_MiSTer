#!/usr/bin/env python3
"""Bind original prompt RAM to the original Macintosh text renderer."""
import importlib.util
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-monitor-prompt-render'
ECHO = HERE.parent / 'card-monitor-key-echo'
TEXT = HERE.parent / 'card-display-text'
spec = importlib.util.spec_from_file_location('prompt_echo_prepare', ECHO / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha
KEY, PROMPT, POST, MATCH = parent.KEY, parent.PROMPT, parent.POST, parent.MATCH
BASE, PARENT = parent.BASE, parent.PARENT


def text_oracle():
    spec = importlib.util.spec_from_file_location('prompt_text_prepare', TEXT / 'prepare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = (TEXT / 'run.py').read_text()
    source = once(source, 'from prepare import HERE, ROOT, WORK, prepare, sha, snapshot_inputs, FIRST_ACK, LAST_ACK', '')
    source = once(source, '    assert seen == set(range(256))', '    assert seen <= set(range(256))')
    namespace = {'__name__': 'prompt_text_oracle', '__file__': str(TEXT / 'run.py'),
                 'ROOT': ROOT, 'snapshot_inputs': module.snapshot_inputs}
    exec(compile(source, str(TEXT / 'run.py'), 'exec'), namespace)
    return namespace, module.snapshot_inputs()[1]


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    oracle, glyph_inputs = text_oracle()
    glyph = WORK / 'glyph.bin'
    glyph.write_bytes(oracle['glyph_state']())
    main = ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin'
    pins = json.loads((HERE.parent / 'card-display-init/results.json').read_text())['inputs_sha256']
    assert sha(main) == pins[str(main)]
    card = WORK / 'card_irq_candidate.sv'
    text = card.read_text()
    text = once(text, 'reg cpu_running, start_pending, armed, report_mode;',
                'reg cpu_running, start_pending, armed, report_mode;\n    reg runtime_paused, runtime_refresh;')
    text = once(text, 'wire runnable = cpu_valid &&', 'wire runnable = (!runtime_paused || cpu_memory_wait) && cpu_valid &&')
    text = re.sub(r'(?m)^( *)armed <= 0;$', r'\1armed <= 0;\n\1runtime_paused <= 0;\n\1runtime_refresh <= 0;', text)
    text = once(text, "                end else if (!sidefx_word && (sidefx_wdata[7:0] & 8'hDF) == 8'h88) begin", '''                end else if (!sidefx_word && sidefx_wdata[7:0] == 8'h80 && armed && reset_mask != 8'hFC) begin
                    runtime_paused <= 1;
                    runtime_refresh <= 1;
                end else if (!sidefx_word && (sidefx_wdata[7:0] & 8'hDF) == 8'h88) begin''')
    text = once(text, '                        armed <= 1;', '                        armed <= 1;\n                        runtime_paused <= 0;')
    text = once(text, '                end else if (cpu_running && (ack || read_release)) fault <= 1;',
                '                end else if (ack && runtime_refresh) runtime_refresh <= 0;\n'
                '                else if (cpu_running && (ack || read_release)) fault <= 1;')
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    start = text.index('        wait(boundary);\n        @(posedge clk_sys);', text.index('        bridge_active = 0;'))
    end = text.index('        $display("EXCHANGE', start)
    checkpoint = text[start:end]
    text = text[:start] + text[end:]
    text = once(text, '    reg [7:0] input_buffer', '''    task render_checkpoint;
        integer page_file;
        begin
''' + checkpoint + '''            page_file = $fopen(live_page_path, "wb");
            if (page_file == 0) $fatal(1, "live page open failed");
            for (integer offset = 0; offset < 1024; offset = offset + 1) $fwrite(page_file, "%c", backing('h400 + offset));
            $fclose(page_file);
            $display("RENDER_READY CPU=%0d writes=%0d captures=%0d", cpu_completed, stores, capture_count);
        end
    endtask
    reg [1023:0] live_page_path;
    reg [7:0] input_buffer''')
    text = once(text, '        $readmemh(image_path, expected);', '''        if (!$value$plusargs("live_page=%s", live_page_path)) $fatal(1, "missing live page path");
        $readmemh(image_path, expected);''')
    text = once(text, 'bridge_index > 512', 'bridge_index > 2048')
    text = once(text, '(bridge_width != 8 && bridge_width != 16)', '(bridge_width != 0 && bridge_width != 8 && bridge_width != 16)')
    text = once(text, '                if (bridge_index == 265) begin', '''                if (bridge_width == 0) begin
                    if (bridge_index != 315 || bridge_write != 0 || bridge_offset != 0 || bridge_value != 0)
                        $fatal(1, "invalid render checkpoint");
                    render_checkpoint();
                    bridge_reply = 0;
                end else begin
                if (bridge_index == 265) begin''')
    text = once(text, '                $display("REPLY %0d %0d", bridge_sequence, bridge_reply);',
                '                end\n                $display("REPLY %0d %0d", bridge_sequence, bridge_reply);')
    # The checkpoint occupies one protocol sequence but creates no PDS request.
    text = once(text, '    reg [1023:0] live_page_path;', '''    integer render_cpu, render_stores, render_captures, empty_acks = 0;
    reg render_started = 0;
    always @(posedge clk_sys) begin
        if (render_started) begin
            if (cpu_completed != 32'(render_cpu) || stores != 32'(render_stores) ||
                capture_count != 32'(render_captures) || capture_valid ||
                dut.platform.card.card.reset_pending || card_cpu_address != 16'hC267)
                $fatal(1, "render hold changed card state");
            if (dut.platform.card.card.ack) begin
                if (!dut.platform.card.card.runtime_refresh) $fatal(1, "unexpected empty render ACK");
                empty_acks = empty_acks + 1;
                $display("RENDER_ACK empty=%0d CPU=%0d captures=%0d", empty_acks, cpu_completed, capture_count);
            end
        end
    end
    reg [1023:0] live_page_path;''')
    text = once(text, '            $display("RENDER_READY', '''            render_cpu = int'(cpu_completed);
            render_stores = int'(stores);
            render_captures = int'(capture_count);
            render_started = 1;
            $display("RENDER_READY''')
    text = once(text, '        $display("EXCHANGE writes=', '''        if (!render_started || empty_acks != 1 || transaction_count != 1371 || bridge_index != 1356 ||
            dut.platform.card.card.runtime_paused || dut.platform.card.card.runtime_refresh)
            $fatal(1, "render endpoint coverage mismatch");
        $display("RENDER_ACCOUNT guest=1354 delivery=1 prelude=16 protocol=1355 total=%0d", transaction_count);
        $display("EXCHANGE writes=''')
    text = once(text, 'capture_count, bridge_index - 1);', 'capture_count, bridge_index - 2);')
    text = once(text, 'PASS key-echo fast=', 'PASS prompt-render fast=')
    bench.write_text(text, encoding='ascii')
    host = WORK / 'host.lua'
    text = host.read_text()
    text = once(text, 'sequence <= 512', 'sequence <= 2048')
    text = once(text, 'if return_writes == 30 then', "if return_writes == 30 and cpu.state['PC'].value >= base + 0x2000 then")
    text = once(text, "assert(count == 1 and (off == 0xc or off == 0x19 or off == 0x21), 'Unexpected PDS write')",
                "assert((count == 1 and (off == 0xc or off == 0x19 or off == 0x21 or off == 0x20 or off == 0xd)) or (count == 2 and off == 0x1c), 'Unexpected PDS write')")
    text = once(text, '            record(true, count * 8, off, value)\n        end)', '''            record(true, count * 8, off, value)
            if off == 0x19 and return_writes == 30 then assert(bridge(false, 0, 0, 0) == 0) end
        end)''')
    text = once(text, 'trace off,:maincpu; quit\')\n        cpu.state[\'A4\']', '''trace off,:maincpu; '
            .. 'd@310000=pc; d@310004=a7; save "' .. run .. '/prefix-state.bin",310000,8; '
            .. 'load "' .. assert(os.getenv('IIE_RENDER_GLYPH')) .. '",2fdbee; '
            .. 'load "' .. assert(os.getenv('IIE_MAIN_CODE')) .. '",280000; '
            .. 'w@(a5-972)=40; d@3efff8=2007ae; d@3efffc=290000; a7=3efff8; pc=284300; '
            .. 'trace ' .. run .. '/render-trace.txt,:maincpu,noloop; g')
        cpu.debug:bpset(0x290000, '1',
            'save "' .. run .. '/render-world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/render-code.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'save "' .. run .. '/render-main.bin",280000,685c; '
            .. 'save "' .. run .. '/render-frame.bin",fffc0,' .. string.format('%x', frame_size + 128) .. '; '
            .. 'd@310010=pc; d@310014=a7; save "' .. run .. '/render-state.bin",310010,8; trace off,:maincpu; quit')
        cpu.state['A4']''')
    text = once(text, '    elseif frames == 3001 then', '''    elseif frames > 3000 then
        local rendered = io.open(run .. '/render-state.bin', 'rb')
        if not rendered then return end
        rendered:close()''')
    if os.environ.get('IIE_RENDER_CONTROL') == 'glyph':
        bitmap = bytearray(glyph.read_bytes())
        bitmap[0x41 * 16 + 1] ^= 4
        glyph.write_bytes(bitmap)
    if os.environ.get('IIE_RENDER_CONTROL') == 'destination':
        text = once(text, 'w@(a5-972)=40;', 'd@(a5-85e)=d@(a5-85e)+1; w@(a5-972)=40;')
    host.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'run.py', HERE / 'checks.py',
        ECHO / 'run.py', TEXT / 'prepare.py', TEXT / 'run.py', main, glyph, *glyph_inputs]
