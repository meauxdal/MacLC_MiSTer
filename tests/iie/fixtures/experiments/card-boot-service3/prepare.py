#!/usr/bin/env python3
"""Continue the original monitor through its first live BS3 return."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-boot-service3'
PARENT = HERE.parent / 'card-boot-service2'
spec = importlib.util.spec_from_file_location('bs3_boot_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    card = WORK / 'card_irq_candidate.sv'
    text = once(card.read_text(), 'reg internal_rom, monitor_done;',
                'reg internal_rom, monitor_done;\n    reg [2:0] service_returns;')
    assert text.count('host_return <= 0;') == 2
    text = text.replace('host_return <= 0;', 'host_return <= 0; service_returns <= 0;')
    text = once(text, 'if (rti_done && nmi_overlay) monitor_done <= 1;',
                "if (rti_done && nmi_overlay) begin monitor_done <= 1; service_returns <= service_returns + 1'b1; end")
    text = once(text, "monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFAC0;",
                "service_returns == 4 && cpu_valid && cpu_sync && cpu_address == 16'hFAC2;")
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    text = text.replace('host_returns >= 10 && register_index == 0',
                        'host_returns >= 10 && host_returns < 15 && register_index == 0')
    text = text.replace('register_reads >= 10 && register_index == 0',
                        'register_reads >= 10 && register_reads < 15 && register_index == 0')
    text = once(text, '            if (capture_address !==',
                "            if (host_returns >= 15 && register_index == 3) return_value = return_value & 8'hFD;\n"
                '            if (capture_address !==')
    text = once(text, "                if (card_cpu_address !== 16'hC078 + 16'(register_index) ||",
                "                if (register_reads >= 15 && register_index == 3) return_value = return_value & 8'hFD;\n"
                "                if (card_cpu_address !== 16'hC078 + 16'(register_index) ||")
    text = once(text, "(card_cpu_address == 16'hFAB6 && register_reads == 15 && rti_contexts == 2)",
                "(card_cpu_address == 16'hFAB6 && register_reads == 15 && rti_contexts == 2) ||\n"
                "             (card_cpu_address == 16'hFAC2 && register_reads == 20 && rti_contexts == 3)")
    text = once(text, 'processor.cpu.reg_p !== saved_p',
                "processor.cpu.reg_p !== (rti_contexts == 3 ? saved_p & 8'hFD : saved_p)")
    text = once(text, 'if (cpu_ready && dut.platform.card.card.cpu_sync &&',
                'if ((cpu_ready || boundary) && dut.platform.card.card.cpu_sync &&')
    text = once(text, '        wait(boundary);\n        @(negedge clk_sys);',
                '        wait(boundary);\n        @(posedge clk_sys);\n        @(negedge clk_sys);')
    text = once(text, "card_cpu_address !== 16'hFAC0 || opcodes != 3 || rtis != 3 || nmis != 3",
                "card_cpu_address !== 16'hFAC2 || opcodes != 4 || rtis != 4 || nmis != 4")
    text = once(text, 'register_writes != 15 || register_reads != 15 || service_writes != 15',
                'register_writes != 20 || register_reads != 20 || service_writes != 20')
    text = once(text, 'host_returns != 15 || switch_services != 5 || rti_contexts != 3',
                'host_returns != 20 || switch_services != 5 || rti_contexts != 4')
    text = once(text, 'capture_count != switch_services + 34', 'capture_count != switch_services + 45')
    text = once(text, 'PASS boot-service2 fast=', 'PASS boot-service3 fast=')
    bench.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'host.lua']
