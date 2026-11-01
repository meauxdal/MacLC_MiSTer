#!/usr/bin/env python3
"""Generate a bounded original diagnostic firmware-vector overlay."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'local/experiments/card-memory-banking'
WORK = ROOT / 'local/experiments/card-firmware-overlay'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    generator = ROOT / 'fixtures/experiments/card-memory-banking/prepare.py'
    manifest = json.loads((ROOT / 'fixtures/experiments/card-memory-banking/results.json').read_text())
    assert sha(generator) == manifest['inputs_sha256'][str(generator)], 'stale memory-banking generator'
    spec = importlib.util.spec_from_file_location('memory_banking_prepare', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WORK = WORK
    closure = module.prepare()
    card = WORK / 'card_irq_candidate.sv'
    assert sha(card) == manifest['inputs_sha256'][str(BASE / card.name)], 'stale generated candidate'
    text = once(card.read_text(), 'parameter IGNORE_ZP_CONTEXT = 0, ALIAS_LC_BANKS = 0) (',
                'parameter IGNORE_ZP_CONTEXT = 0, ALIAS_LC_BANKS = 0,\n'
                '                            IGNORE_FW_OVERLAY = 0) (')
    text = once(text, "cpu_address == 16'h2046;", "cpu_address == 16'h204F;")
    text = once(text, "cpu_address == 16'hC02B || (cpu_write &&",
                "cpu_address == 16'hC02B || (cpu_write && cpu_address == 16'hC028) || (cpu_write &&")
    text = once(text, "? 18'h23FFA + {2'b0, cpu_address} - 18'h0FFFA :",
                "? (card_mode[3] ? 18'h2FFFA : 18'h23FFA) + {2'b0, cpu_address} - 18'h0FFFA :")
    text = once(text, "                if (cpu_write && cpu_address == 16'hC02B) card_mode <= cpu_wdata;",
                "                if (cpu_write && cpu_address == 16'hC02B) card_mode <= cpu_wdata;\n"
                "                if (cpu_write && cpu_address == 16'hC028 && cpu_wdata[7] && !IGNORE_FW_OVERLAY)\n"
                "                    card_mode[3] <= 1;")
    card.write_text(text, encoding='ascii')
    return closure


if __name__ == '__main__':
    prepare()
