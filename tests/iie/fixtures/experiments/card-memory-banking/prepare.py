#!/usr/bin/env python3
"""Generate bounded original diagnostic memory-bank support."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'local/experiments/card-softswitch'
WORK = ROOT / 'local/experiments/card-memory-banking'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    generator = ROOT / 'fixtures/experiments/card-softswitch/prepare.py'
    manifest = json.loads((ROOT / 'fixtures/experiments/card-softswitch/results.json').read_text())
    assert sha(generator) == manifest['inputs_sha256'][str(generator)], 'stale softswitch generator'
    spec = importlib.util.spec_from_file_location('softswitch_prepare', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WORK = WORK
    closure = module.prepare()
    card = WORK / 'card_irq_candidate.sv'
    assert sha(card) == manifest['inputs_sha256'][str(BASE / card.name)], 'stale generated candidate'
    text = once(card.read_text(), "parameter [7:0] SOFTSWITCH_STUCK_MASK = 8'h00) (",
                "parameter [7:0] SOFTSWITCH_STUCK_MASK = 8'h00,\n"
                '                            parameter IGNORE_ZP_CONTEXT = 0, ALIAS_LC_BANKS = 0) (')
    text = once(text, "cpu_address == 16'h2043;", "cpu_address == 16'h2046;")
    text = once(text, '    reg [7:0] display_switches;', '    reg [7:0] display_switches, card_mode;')
    text = once(text, 'wire allowed_io = io_trap || display_switch ||',
                "wire allowed_io = io_trap || display_switch || cpu_address == 16'hC02B ||")
    text = once(text, "cpu_address == 16'hC008 || cpu_address == 16'hC009))",
                "cpu_address == 16'hC008 || cpu_address == 16'hC009 ||\n"
                "                                               cpu_address == 16'hC002 || cpu_address == 16'hC003))")
    text = once(text, "cpu_address == 16'hC019 || cpu_address == 16'hC082));",
                "cpu_address == 16'hC019 || cpu_address == 16'hC082 ||\n"
                "                                      cpu_address == 16'hC083 || cpu_address == 16'hC08B));")
    text = once(text, '    wire firmware_read =', '''    wire language_access = (cpu_address == 16'hD000 || cpu_address == 16'hE000) &&
                           (cpu_write ? high_write : high_read);
    wire alternate_zp = card_mode[4] && !IGNORE_ZP_CONTEXT && effective_ram[16] &&
                        cpu_address == 16'h0000;
    wire unsupported_alternate_zp = card_mode[4] && effective_ram[16] &&
                                    cpu_address < 16'h0200 && cpu_address != 16'h0000;
    wire firmware_read =''')
    text = once(text, "wire [17:0] physical = firmware_test ? 18'h26000 :",
                "wire [17:0] physical = alternate_zp ? 18'h30000 :\n"
                "        language_access && ALIAS_LC_BANKS && cpu_address == 16'hD000\n"
                "        ? {1'b0, effective_ram[16], 4'hD, effective_ram[11:0]} :\n"
                "        firmware_test ? 18'h26000 :")
    text = once(text, 'wire unsupported_cpu = (io_space && !allowed_io) ||',
                'wire unsupported_cpu = unsupported_alternate_zp || (io_space && !allowed_io) ||')
    text = once(text, '!io_space && !firmware_read && !firmware_test && cpu_address',
                '!io_space && !firmware_read && !firmware_test && !language_access && cpu_address')
    text = once(text, "            16'hC019: cpu_rdata = {control[6], 7'b0};",
                "            16'hC019: cpu_rdata = {control[6], 7'b0};\n"
                "            16'hC02B: cpu_rdata = card_mode;")
    text = once(text, '\n            display_switches <= 0;', '\n            display_switches <= 0;\n            card_mode <= 0;')
    text = once(text, '\n                        display_switches <= 0;',
                '\n                        display_switches <= 0;\n                        card_mode <= 0;')
    text = once(text, '                cpu_completed <= cpu_completed + 1;',
                "                cpu_completed <= cpu_completed + 1;\n"
                "                if (cpu_write && cpu_address == 16'hC02B) card_mode <= cpu_wdata;")
    card.write_text(text, encoding='ascii')
    return closure


if __name__ == '__main__':
    prepare()
