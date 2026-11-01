#!/usr/bin/env python3
"""Continue the monitor after its first receiver return."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = ROOT / 'fixtures/experiments/card-monitor-entry'
spec = importlib.util.spec_from_file_location('monitor_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
BASE_WORK = parent.WORK
WORK = ROOT / 'local/experiments/card-monitor-resume'
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    closure, inputs = parent.prepare()
    pins_path = PARENT / 'results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for path in closure:
        original = BASE_WORK / path.name if path.parent == WORK else path
        assert sha(path) == pins[str(original)], 'changed monitor input: ' + str(original)
    card = WORK / 'card_irq_candidate.sv'
    text = once(card.read_text(), '#(parameter [2:0]', '#(parameter FIXED_CX = 0, parameter [2:0]')
    text = once(text, '    reg slot3_rom;', '    reg slot3_rom, internal_c8;')
    text = once(text,
                "    wire monitor_read = !cpu_write && cpu_address >= 16'hC100 && !high_read;",
                """    wire internal_cx = internal_rom ||
        (cpu_address[15:8] == 8'hC3 && !slot3_rom) ||
        (cpu_address >= 16'hC800 && internal_c8);
    wire monitor_read = !cpu_write &&
        ((cpu_address >= 16'hD000 && !high_read) ||
         (cpu_address >= 16'hC100 && cpu_address < 16'hD000 && (FIXED_CX || internal_cx)));""")
    text = once(text, '    wire service_register =', """    wire slot3_read = !cpu_write && cpu_address[15:8] == 8'hC3 && !internal_cx && !FIXED_CX;
    wire cfff_read = !cpu_write && cpu_address == 16'hCFFF && !internal_cx && !FIXED_CX;
    wire service_register =""")
    text = once(text, 'wire [17:0] physical = receiver_read ?',
                "wire [17:0] physical = slot3_read ? 18'h2C300 + {10'b0, cpu_address[7:0]} : receiver_read ?")
    text = once(text, '!io_space && !monitor_read && !receiver_read',
                '!io_space && !slot3_read && !cfff_read && !monitor_read && !receiver_read')
    text = once(text, "            16'hC07D: cpu_rdata = 8'hA5;",
                "            16'hCFFF: if (cfff_read) cpu_rdata = FLOATING_DATA;\n"
                "            16'hC07D: cpu_rdata = 8'hA5;")
    assert sum(line.strip() == 'slot3_rom <= 0;' for line in text.splitlines()) == 2
    lines = []
    for line in text.splitlines():
        lines.append(line)
        if line.strip() == 'slot3_rom <= 0;':
            lines.append(line[:len(line) - len(line.lstrip())] + 'internal_c8 <= 0;')
    text = '\n'.join(lines) + '\n'
    text = once(text, '                cpu_completed <= cpu_completed + 1;',
                """                cpu_completed <= cpu_completed + 1;
                if (cpu_address[15:8] == 8'hC3 && !slot3_rom) internal_c8 <= 1;
                else if (cpu_address == 16'hCFFF) internal_c8 <= 0;""")
    text = once(text,
                'assign boundary = monitor_done && cpu_valid && cpu_sync;',
                "assign boundary = monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFB63;")
    card.write_text(text, encoding='ascii')
    source = ROOT / 'local/experiments/card-cpu-rtl/source/apple2.v'
    source_pins = ROOT / 'fixtures/experiments/card-cpu-rtl/results.json'
    pins = json.loads(source_pins.read_text())['inputs_sha256']
    assert sha(source) == pins['archive:rtl/apple2.v'], 'changed Apple II source'
    return closure, inputs + [Path(__file__), PARENT / 'prepare.py', pins_path, source, source_pins]


if __name__ == '__main__':
    prepare()
