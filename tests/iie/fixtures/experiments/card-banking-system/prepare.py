#!/usr/bin/env python3
"""Generate a bounded zero-page/protection variant of the IRQ candidate."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def generate(work):
    source = ROOT / 'fixtures/experiments/card-irq-system/prepare.py'
    spec = importlib.util.spec_from_file_location('irq_prepare', source)
    irq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(irq)
    outputs = irq.generate(work)
    card = outputs[2]
    text = card.read_text()
    text = once(text, 'NMI_DELAY = 0, IRQ_DELAY = 0) (',
                'NMI_DELAY = 0, IRQ_DELAY = 0,\n'
                '                            IGNORE_AUX_INHIBIT = 0, IGNORE_FW_PROTECT = 0) (')
    text = once(text, "cpu_address == 16'h203A;", "cpu_address == 16'h2040;")
    text = once(text, "cpu_address == 16'hC004 || cpu_address == 16'hC005",
                "cpu_address == 16'hC004 || cpu_address == 16'hC005 ||\n"
                "                                               cpu_address == 16'hC008 || cpu_address == 16'hC009")
    text = once(text, "cpu_address == 16'hC019));",
                "cpu_address == 16'hC019 || cpu_address == 16'hC082));")
    text = once(text, '    wire firmware_read =', '''    // Candidate controls, bounded to the original zero-page and E000 tests.
    wire aux_inhibit = control[2] && !IGNORE_AUX_INHIBIT && cpu_address < 16'h0200;
    wire [16:0] effective_ram = {ram_address[16] && !aux_inhibit, ram_address[15:0]};
    wire firmware_test = cpu_address == 16'hE000 && !high_read;
    wire protected_write = firmware_test && cpu_write && !control[4] && !IGNORE_FW_PROTECT;
    wire firmware_read =''')
    text = once(text, "    wire [17:0] physical = firmware_read ?", "    wire [17:0] physical = firmware_test ? 18'h26000 :\n        firmware_read ?")
    text = once(text, "{1'b0, ram_address};", "{1'b0, effective_ram};")
    text = once(text, '!io_space && !firmware_read && cpu_address', '!io_space && !firmware_read && !firmware_test && cpu_address')
    text = once(text, '!io_space && !cpu_memory_wait;', '!io_space && !protected_write && !cpu_memory_wait;')
    text = once(text, '(io_space ? allowed_io : (cpu_memory_wait && master_rsp_valid[1]));',
                '(io_space ? allowed_io : (protected_write || (cpu_memory_wait && master_rsp_valid[1])));')
    card.write_text(text, encoding='ascii')
    return outputs


if __name__ == '__main__':
    generate(ROOT / 'local/experiments/card-banking-system')
