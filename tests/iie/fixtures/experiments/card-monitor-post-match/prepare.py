#!/usr/bin/env python3
"""Continue the original monitor into Applesoft cold-start RAM sizing."""
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-monitor-post-match'
PARENT = HERE.parent / 'card-boot-service2'
BASE = HERE.parent / 'card-boot-service3'
MATCH = HERE.parent / 'card-boot-service3-live-match'
spec = importlib.util.spec_from_file_location('post_match_prepare', MATCH / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    card = WORK / 'card_irq_candidate.sv'
    text = once(card.read_text(), "service_returns == 5 && cpu_valid && cpu_sync && cpu_address == 16'hFA9B;",
        "service_returns == 5 && cpu_valid && cpu_sync && cpu_address == 16'hF183 &&\n"
        "        processor.cpu.reg_y == 0 &&\n"
        "        processor.cpu.reg_s == 8'hFA && sizing_page == 8'hC0;")
    text = once(text, '    reg [2:0] service_returns;', '''    reg [2:0] service_returns;
    reg [7:0] sizing_page;
    always @(posedge clk) begin
        if (!por_n || !cpu_running) sizing_page <= 0;
        else if (cpu_ready && cpu_write && cpu_address == 16'h0051)
            sizing_page <= cpu_wdata;
    end''')
    text = once(text, '    wire [17:0] physical =',
        "    wire [17:0] physical = cpu_address == 16'hE000 && $test$plusargs(\"wrong_e000\") ? 18'h26000 :")
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = once(bench.read_text(), "card_cpu_address !== 16'hFA9B || opcodes", "card_cpu_address !== 16'hF183 || opcodes")
    text = once(text, "expected[1] !== 8'hC4 ||\n            dut.platform.card.card.processor.cpu.reg_a !== 8'hC4",
        "expected[1] !== 8'h28 || expected[2] !== 8'hF1 ||\n            expected['h3F2] !== 3 || expected['h51] !== 8'hC0")
    start = text.index("        if (expected[0] !== 0 || expected[1] !== 8'(boot_a - 2)")
    end = text.index('        $display("EXCHANGE writes=', start)
    text = text[:start] + (HERE / 'sizing.sv').read_text() + text[end:]
    text = once(text, '    integer external_reads = 0;', '''    integer external_reads = 0;
    integer cold_entries = 0, probe_count = 0, probe_writes = 0;
    reg [7:0] original_probe [0:191];
    always @(posedge clk_sys) begin
        if (cpu_ready && dut.platform.card.card.service_returns == 5) begin
            if (dut.platform.card.card.cpu_sync && card_cpu_address == 16'hE000) begin
                if (dut.platform.card.card.physical !== 18'h22000 ||
                    dut.platform.card.card.cpu_rdata !== 8'h4C)
                    $fatal(1, "cold E000 routing mismatch physical=%h data=%h",
                           dut.platform.card.card.physical, dut.platform.card.card.cpu_rdata);
                cold_entries = cold_entries + 1;
            end
            if (dut.platform.card.card.cpu_sync && card_cpu_address == 16'hF183) begin
                if (expected['h51] !== 8'(9 + probe_count) || expected['h50] !== 0)
                    $fatal(1, "cold sizing probe order");
                original_probe[probe_count] = expected[(9 + probe_count) * 256];
                probe_count = probe_count + 1;
            end
            if (dut.platform.card.card.cpu_write && card_cpu_address >= 16'h0900 &&
                card_cpu_address < 16'hC000 && card_cpu_address[7:0] == 0) begin
                if (card_cpu_address[15:8] !== 8'(9 + probe_writes / 2) ||
                    dut.platform.card.card.cpu_wdata !==
                        (probe_writes[0] ? original_probe[probe_writes / 2] : ~original_probe[probe_writes / 2]))
                    $fatal(1, "cold sizing write mismatch");
                probe_writes = probe_writes + 1;
            end
        end
    end''')
    text = once(text, 'PASS matching-bs3 fast=', 'PASS post-match fast=')
    if os.environ.get('IIE_FINISH_INIT') == '1':
        text = once(text, "card_cpu_address !== 16'hF183 || opcodes", "card_cpu_address !== 16'hF1D2 || opcodes")
        text = once(text, "expected[1] !== 8'h28 || expected[2] !== 8'hF1", "expected[1] !== 8'h3C || expected[2] !== 8'hD4")
        text = once(text, 'probe_count != 183', 'probe_count != 184')
        text = once(text, "expected[4] !== 8'h28 || expected[5] !== 8'hF1", "expected[4] !== 8'h3A || expected[5] !== 8'hDB")
        text = once(text, "processor.cpu.reg_s !== 8'hFA)", "processor.cpu.reg_s !== 8'hF8)")
        text = once(text, "if (expected['hB0 + i] !== expected['h20000 + 'h310A + i])",
                    "if (expected['hB0 + i] !== (i == 8 ? 8'h00 : i == 9 ? 8'h08 : expected['h20000 + 'h310A + i]))")
        text = once(text, '        $display("SIZING entries=', '''        if (expected['h73] !== 0 || expected['h74] !== 8'hC0 ||
            expected['h6F] !== 0 || expected['h70] !== 8'hC0 ||
            expected['h67] !== 1 || expected['h68] !== 8'h08 ||
            expected['h69] !== 3 || expected['h6A] !== 8'h08 ||
            expected['h6B] !== 3 || expected['h6C] !== 8'h08 ||
            expected['h6D] !== 3 || expected['h6E] !== 8'h08 ||
            expected['hAF] !== 3 || expected['hB0] !== 8'h08)
            $fatal(1, "cold-start memory limits or NEW pointers mismatch");
        $display("SIZING entries=''')
        text = once(text, 'capture_count != switch_services + 56', 'capture_count != switch_services + 57')
        text = once(text, "if (capture_status != 8'h08 ||", "if (capture_status != 8'hE0 ||")
        pins_path = HERE.parent / 'card-display-switches/results.json'
        pinned = ROOT / 'local/experiments/card-display-switches/card_irq_candidate.sv'
        assert sha(pinned) == json.loads(pins_path.read_text())['inputs_sha256'][str(pinned)]
        assert "else if (display_switch) capture_status <= 8'hE0;" in pinned.read_text()
        inputs += [pins_path, pinned, HERE.parent / 'card-display-switches/prepare.py']
        candidate = card.read_text()
        candidate = once(candidate, "else if (display_switch) capture_status <= 8'h08;",
                         "else if (display_switch) capture_status <= 8'hE0;")
        start = candidate.index('    assign boundary =')
        end = candidate.index('    assign master_valid[1]', start)
        candidate = candidate[:start] + "    assign boundary = service_returns == 5 && cpu_valid && cpu_sync && cpu_address == 16'hF1D2;\n" + candidate[end:]
        card.write_text(candidate, encoding='ascii')
        host = WORK / 'host.lua'
        lua = once(host.read_text(), 'local frames, sequence, service_acks, return_writes = 0, 0, 0, 0',
                   'local frames, sequence, service_acks, return_writes = 0, 0, 0, 0\nlocal cold_acks = 0')
        lua = once(lua, 'if return_writes == 25 then', 'if return_writes == 25 and cold_acks == 1 then')
        lua = once(lua, "                if cpu.state['PC'].value == base + 0x1cb2 then", """                if return_writes == 25 and cpu.state['PC'].value ~= base + 0x1cb2 then
                    cold_acks = cold_acks + 1
                    assert(cold_acks == 1, 'Extra cold-start switch ACK')
                    snapshot('cold-switch-world.bin', world - 0x5960, 0x5c49)
                    snapshot('cold-switch-code.bin', base, #bytes)
                end
                if cpu.state['PC'].value == base + 0x1cb2 then""")
        lua = once(lua, "'temp0=0; temp1=0; temp2=0; temp3=0'", "'temp0=0; temp1=0; temp2=0; temp3=0; temp4=0'")
        lua = once(lua, "        cpu.debug:bpset(base + 0x281c, 'temp0==3',", """        cpu.debug:bpset(base + 0x1584, 'temp0==3', 'temp4=1; g')
        cpu.debug:bpset(base + 0x281c, 'temp0==3 && temp4==1',""")
        if os.environ.get('IIE_WRONG_SWITCH') == '1':
            card.write_text(once(card.read_text(), "else if (display_switch) capture_status <= 8'hE0;",
                                 "else if (display_switch) capture_status <= 8'h08;"), encoding='ascii')
            text = once(text, "if (capture_status != 8'hE0 ||", "if (capture_status != 8'h08 ||")
            lua = once(lua, "        cpu.state['A4'].value = card", """        cpu.debug:bpset(base + 0x28c6, 'temp0==3',
            'save "' .. run .. '/world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/cold-route-world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'trace off,:maincpu; quit')
        cpu.state['A4'].value = card""")
            lua = once(lua, '            local result = bridge(false, count * 8, off, 0)', """            if return_writes == 25 and off == 4 then
                local terminal = assert(io.open(run .. '/cold-route-world.bin', 'rb'))
                terminal:close()
                return data & ~mask
            end
            local result = bridge(false, count * 8, off, 0)""")
        host.write_text(lua, encoding='ascii')
    bench.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'sizing.sv', HERE / 'checks.py']
