#!/usr/bin/env python3
"""Extend the live register exchange through original boot service 2."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-boot-service2'
PARENT = HERE.parent / 'card-saved-register-live'
spec = importlib.util.spec_from_file_location('boot_saved_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    candidate = WORK / 'card_irq_candidate.sv'
    candidate.write_text(once(candidate.read_text(), "cpu_address == 16'hFAB4;",
                              "cpu_address == 16'hFAC0;"), encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    text = once(text, '    integer register_writes = 0,',
                '    integer boot_a = 198;\n    integer register_writes = 0,')
    text = once(text, '        $readmemh(image_path, expected);',
                '        if ($value$plusargs("boot_a=%d", boot_a)) begin end\n'
                '        $readmemh(image_path, expected);')
    text = text.replace('host_returns >= 5 && register_index == 2',
                        'host_returns >= 5 && host_returns < 10 && register_index == 2')
    text = text.replace('register_reads >= 5 && register_index == 2',
                        'register_reads >= 5 && register_reads < 10 && register_index == 2')
    text = once(text, '            if (capture_address !==',
                '            if (host_returns >= 10 && register_index == 0) return_value = 8\'(boot_a);\n'
                '            if (capture_address !==')
    text = once(text, '                if (card_cpu_address !== 16\'hC078 + 16\'(register_index) ||',
                '                if (register_reads >= 10 && register_index == 0) return_value = 8\'(boot_a);\n'
                '                if (card_cpu_address !== 16\'hC078 + 16\'(register_index) ||')
    text = once(text, "(card_cpu_address == 16'hFB65 && register_reads == 10 && rti_contexts == 1)",
                "(card_cpu_address == 16'hFB65 && register_reads == 10 && rti_contexts == 1) ||\n"
                "             (card_cpu_address == 16'hFAB6 && register_reads == 15 && rti_contexts == 2)")
    text = once(text, "rtis != (card_cpu_address == 16'hFBDF ? 1 : 2)", 'rtis != rti_contexts + 1')
    text = once(text, 'processor.cpu.reg_a !== saved_a',
                "processor.cpu.reg_a !== (rti_contexts == 2 ? 8'(boot_a) : saved_a)")
    text = once(text, "(card_cpu_address == 16'hFBDF ? saved_y : 8'd9)",
                "(rti_contexts == 1 ? 8'd9 : saved_y)")
    text = once(text, "card_cpu_address !== 16'hFAB4 || opcodes != 2 || rtis != 2 || nmis != 2",
                "card_cpu_address !== 16'hFAC0 || opcodes != 3 || rtis != 3 || nmis != 3")
    text = once(text, 'register_writes != 10 || register_reads != 10 || service_writes != 10',
                'register_writes != 15 || register_reads != 15 || service_writes != 15')
    text = once(text, 'host_returns != 10 || switch_services != 5 || rti_contexts != 2',
                'host_returns != 15 || switch_services != 5 || rti_contexts != 3')
    text = once(text, 'capture_count != switch_services + 23', 'capture_count != switch_services + 34')
    text = once(text, '        $display("EXCHANGE writes=', '''        if (expected[0] !== 0 || expected[1] !== 8'(boot_a - 1) ||
            dut.platform.card.card.processor.cpu.reg_a !== 8'(boot_a - 1) ||
            dut.platform.card.card.processor.cpu.reg_y !== 5)
            $fatal(1, "boot monitor continuation mismatch");
        $display("BOOT A=%h next_A=%h page=%h next_PC=%h", 8'(boot_a),
                 dut.platform.card.card.processor.cpu.reg_a, expected[1], card_cpu_address);
        $display("EXCHANGE writes=''')
    text = once(text, 'PASS saved-register fast=', 'PASS boot-service2 fast=')
    bench.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'host.lua']
