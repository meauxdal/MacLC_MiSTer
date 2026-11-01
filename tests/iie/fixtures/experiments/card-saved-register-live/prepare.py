#!/usr/bin/env python3
"""Generate a saved-register trap candidate from pinned monitor sources."""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-saved-register-live'
BASE = ROOT / 'local/experiments/card-monitor-resume'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare():
    pins_path = ROOT / 'fixtures/experiments/card-monitor-resume/results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    originals = [Path(p) for p in names[names.index(str(binding)):] if Path(p).suffix in ('.v', '.sv')]
    originals.append(ROOT / 'fixtures/experiments/card-cpu-pacing/card_cycle_pacer.sv')
    original, image = BASE / 'tb_monitor.sv', BASE / 'initial.hex'
    for path in [original, image, *originals]:
        assert sha(path) == pins[str(path)], 'changed pinned source: ' + str(path)
    WORK.mkdir(parents=True, exist_ok=True)
    mask_pins_path = ROOT / 'fixtures/experiments/card-service4-render/results.json'
    mask_registers = ROOT / 'local/experiments/card-display-mask/card_irq_host_registers.sv'
    assert sha(mask_registers) == json.loads(mask_pins_path.read_text())['inputs_sha256'][str(mask_registers)]
    sources = []
    for path in originals:
        if path.name == 'card_irq_host_registers.sv':
            sources.append(mask_registers)
            continue
        if path.parent != BASE:
            sources.append(path)
            continue
        text = path.read_text()
        if path.name == 'card_irq_candidate.sv':
            text = once(text, 'reg [7:0] service_regs [0:4];', 'reg [7:0] host_return;')
            text = re.sub(r'(?m)^ *service_regs\[[0-4]\] <= 0;\n', '', text)
            text = once(text, 'if (cpu_write && service_register) service_regs[cpu_address[2:0]] <= cpu_wdata;',
                        '')
            text = once(text, 'cpu_rdata = service_regs[cpu_address[2:0]];', 'cpu_rdata = host_return;')
            text = once(text, 'wire io_trap =', 'wire io_trap = service_register ||')
            text = once(text, "monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFB63;",
                        "monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFAB4;")
            text = once(text, "capture_read_release <= cpu_address == 16'hC07D && !cpu_write;",
                        "capture_read_release <= (service_register || cpu_address == 16'hC07D) && !cpu_write;")
            text = once(text, "else if (cpu_address == 16'hC07D) capture_status <= cpu_write ? 8'hE0 : 8'hE1;",
                        "else if (service_register || cpu_address == 16'hC07D) capture_status <= cpu_write ? 8'hE0 : 8'hE1;")
            text = once(text, "if (sidefx_write && sidefx_wdata[7:0] != 0) fault <= 1;",
                        "if (sidefx_write && !read_release && sidefx_wdata[7:0] != 0) fault <= 1;")
            text = once(text, '        if (!por_n) begin\n            nmi_pending <= 0;',
                        '        if (!por_n) begin\n            host_return <= 0;\n            nmi_pending <= 0;')
            text = once(text, '            if (reset_commit) begin',
                        '            if (reset_commit) begin\n                host_return <= 0;')
            text = once(text, '            if (mask_write)',
                        '            if (read_release && capture_valid && capture_read_release)\n'
                        '                host_return <= sidefx_wdata[7:0];\n            if (mask_write)')
            assert 'service_regs' not in text
        target = WORK / path.name
        target.write_text(text, encoding='ascii')
        sources.append(target)
    text = original.read_text()
    text = once(text, '    reg poll_empty = 0;', '''    reg bridge_active = 0;
    integer bridge_reply, bridge_sequence, bridge_write, bridge_width, bridge_offset, bridge_value;
    integer bridge_fields, bridge_index;
    reg poll_empty = 0;''')
    text = once(text, '            poll_empty = write_arg == 0', '''            if (bridge_active) begin
                expected_data = pds_read_data;
                bridge_reply = write_arg != 0 ? value_arg : word_arg != 0 ?
                    {16'b0, pds_read_data} : offset_arg[0] ?
                    {24'b0, pds_read_data[7:0]} : {24'b0, pds_read_data[15:8]};
            end
            poll_empty = !bridge_active && write_arg == 0''')
    text = once(text, "while (capture_address != 16'hC07D) begin",
                "while (capture_address != 16'hC078) begin")
    start = text.index('        $display("MONITOR report')
    end = text.index('        stop_competitors = 1;', start)
    text = text[:start] + (HERE / 'sequence.sv').read_text() + text[end:]
    text = once(text, 'capture_count != switch_services + 2 || capture_valid ||',
                'capture_count != switch_services + 23 || capture_valid ||')
    start = text.index('        for (i = 0; i < 1024; i = i + 1) begin', text.index('monitor memory transport mismatch'))
    end = text.index('        if (cx_reads == 0', start)
    text = text[:start] + text[end:]
    text = once(text, 'PASS monitor fast=', 'PASS saved-register fast=')
    text = once(text, '    integer service_writes = 0,',
                (HERE / 'checks.sv').read_text() + '\n    integer service_writes = 0,')
    bench = WORK / 'tb_saved_register.sv'
    bench.write_text(text, encoding='ascii')
    return [bench, *sources], image, [pins_path, original, image, *originals,
        HERE / 'prepare.py', HERE / 'sequence.sv', HERE / 'checks.sv', HERE / 'host.lua',
        mask_pins_path, mask_registers]
