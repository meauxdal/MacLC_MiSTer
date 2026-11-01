#!/usr/bin/env python3
"""Run original Monx loading into initially empty native card RAM."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-normal-upload'
CONTINUOUS = HERE.parent / 'card-continuous-glyph'
spec = importlib.util.spec_from_file_location('upload_continuous_prepare', CONTINUOUS / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha, text_oracle = parent.once, parent.sha, parent.text_oracle
POLL, RENDER, ECHO, KEY, PROMPT, POST, MATCH = parent.POLL, parent.RENDER, parent.ECHO, parent.KEY, parent.PROMPT, parent.POST, parent.MATCH
BASE, PARENT = parent.BASE, parent.PARENT


def prepare():
    parent.WORK = WORK
    sources, _, inputs = parent.prepare()
    card = WORK / 'card_irq_candidate.sv'
    candidate = once(card.read_text(), "sidefx_wdata[7:0] == 8'h80 && reset_mask == 8'hFC",
                     "sidefx_wdata[7:0] == 8'h80 && (reset_mask == 8'hFC || !cpu_running)")
    candidate = once(candidate, '(!capture_valid || !capture_write);',
                     '(cpu_running && !capture_valid && !runtime_refresh);')
    card.write_text(candidate, encoding='ascii')
    registers = next(path for path in sources if path.name == 'card_irq_host_registers.sv')
    text = once(registers.read_text(), "{1'b0, 6'h20}: rsp_rdata <= {8'b0, command_byte};",
                "{1'b0, 6'h20}: rsp_rdata <= {8'b0, command_byte};\n"
                "                                {1'b1, 6'h20}: rsp_rdata <= {command_byte, host_mask};")
    patched = WORK / registers.name
    patched.write_text(text, encoding='ascii')
    sources = [patched if path == registers else path for path in sources]
    image = WORK / 'empty.hex'
    image.write_text('00\n' * 262144, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    text = once(text, '    reg bridge_active = 0;', '    integer host_writes = 0;\n    reg bridge_active = 0;')
    text = once(text, 'stores != ram_writes ||', 'stores != ram_writes + host_writes ||')
    text = once(text, "expected['h10400 + text_address] !== 0)", "expected['h10400 + text_address] !== 8'hA0)")
    start = text.index('        transact(1, 0, 33, 252, 0);')
    end = text.index('        bridge_active = 1;', start)
    text = text[:start] + text[end:]
    text = once(text, 'bridge_index > 16384', 'bridge_index > 262144')
    text = once(text, 'ticks > 8000000', 'ticks > 40000000')
    text = once(text, '                if (!bridge_write && bridge_offset == 1 &&', '''                if (bridge_width == 0) begin
                    if (bridge_write || bridge_offset || bridge_value != 85 ||
                        dut.platform.card.card.cpu_running || cpu_completed != 0)
                        $fatal(1, "invalid upload completion");
                    $display("UPLOAD_COMPLETE requests=%0d writes=%0d", bridge_index - 1, stores);
                    wait(dut.platform.card.card.drained);
                    if (stores != host_writes) $fatal(1, "upload commit mismatch");
                    bridge_reply = 0;
                end else begin
                if (bridge_write && (bridge_offset == 16 || bridge_offset == 17)) begin
                    host_writes = host_writes + (bridge_width == 16 ? 2 : 1);
                    if (bridge_width == 16) begin
                        expected[{dut.platform.card.card.control[3], 1'b0,
                                  dut.platform.card.card.host_index}] = 8'(bridge_value >> 8);
                        expected[{dut.platform.card.card.control[3], 1'b1,
                                  dut.platform.card.card.host_index}] = 8'(bridge_value);
                    end else expected[{dut.platform.card.card.control[3], bridge_offset[0],
                                       dut.platform.card.card.host_index}] = 8'(bridge_value);
                end
                if (!bridge_write && bridge_offset == 1 &&''')
    text = once(text, '                $display("REPLY', '                end\n                $display("REPLY')
    bench.write_text(text, encoding='ascii')
    host = WORK / 'host.lua'
    text = host.read_text().replace('sequence <= 16384', 'sequence <= 262144')
    text = once(text, "        bp(base + 0x2d4, '1', 'pc=20281c; g')\n", '')
    text = once(text, 'off == 0x20 or off == 0xd', 'off == 0x20 or off == 0xd or off == 0x10 or off == 0x11')
    text = once(text, '(count == 2 and off == 0x1c)', '(count == 2 and (off == 0x1c or off == 0x10 or off == 0x20))')
    text = once(text, "        cpu.state['PC'].value = base + 0x4a", '''        bp(live.main + 0x5c8, '1',
            'save "' .. run .. '/upload-code.bin",280000,685c; '
            .. 'pc=28069a; g')
        bp(live.main + 0x69a, '1',
            'b@310040=1; g')
        local upload_tap = space:install_write_tap(live.control + 0x40, live.control + 0x43,
            'upload-finish', function()
                assert(bridge(false, 0, 0, 85) == 0)
            end)
        _G.iie_upload_tap = upload_tap
        space:write_u32(relocate(0x3efff0), live.main + 0x4300)
        space:write_u32(relocate(0x3efff4), live.main + 0x46a)
        space:write_u32(relocate(0x3efff8), base + 0x450)
        space:write_u32(relocate(0x3efffc), base + 0x281c)
        cpu.state['A7'].value = relocate(0x3efff0)
        cpu.state['PC'].value = base + 0x4a''')
    host.write_text(text, encoding='ascii')
    return sources, image, inputs + [image, HERE / 'prepare.py', HERE / 'run.py', HERE / 'checks.py']
