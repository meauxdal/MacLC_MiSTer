#!/usr/bin/env python3
"""Generate a separate bounded display-softswitch candidate."""
import hashlib
import importlib.util
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'local/experiments/maclc-iie-banking-build'
WORK = ROOT / 'local/experiments/card-softswitch'
ON = (0xC00F, 0xC051, 0xC057, 0xC05F, 0xC00D, 0xC053, 0xC055, 0xC001)
OFF = tuple(address - 1 for address in ON)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    generator = ROOT / 'fixtures/experiments/card-banking-system/prepare.py'
    spec = importlib.util.spec_from_file_location('banking_prepare', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs = module.generate(WORK)
    card = outputs[2]
    text = once(card.read_text(), 'IGNORE_FW_PROTECT = 0) (',
                "IGNORE_FW_PROTECT = 0, IGNORE_SOFTSWITCH = 0,\n"
                "                            parameter [7:0] SOFTSWITCH_STUCK_MASK = 8'h00) (")
    text = once(text, "cpu_address == 16'h2040;", "cpu_address == 16'h2043;")
    decode = ' ||\n                       '.join(f"cpu_address == 16'h{address:04X}" for address in ON + OFF)
    text = once(text, '    wire trap =', '    reg [7:0] display_switches;\n'
                '    wire display_switch = cpu_write && (' + decode + ');\n    wire trap =')
    text = once(text, 'wire trap = reset_vector || io_trap ||',
                'wire trap = reset_vector || io_trap || display_switch ||')
    text = once(text, 'wire allowed_io = io_trap ||', 'wire allowed_io = io_trap || display_switch ||')
    text = once(text, ".opaque08(8'b0)", '.opaque08(display_switches)')
    text = once(text, '\n            keyboard <= 0;', '\n            keyboard <= 0;\n            display_switches <= 0;')
    text = once(text, '\n                        keyboard <= 0;',
                '\n                        keyboard <= 0;\n                        display_switches <= 0;')
    cases = ''.join(f"                        16'h{on:04X}, 16'h{off:04X}:\n"
                    f"                            if (!SOFTSWITCH_STUCK_MASK[{bit}]) display_switches[{bit}] <= cpu_address[0];\n"
                    for bit, (on, off) in enumerate(zip(ON, OFF)))
    text = once(text, '                capture_reset <= reset_vector;',
                '                // Host status includes the held access before its ACK.\n'
                '                if (display_switch && !IGNORE_SOFTSWITCH) begin\n'
                '                    case (cpu_address)\n' + cases +
                '                        default: ;\n                    endcase\n                end\n'
                '                capture_reset <= reset_vector;')
    text = once(text, "                else if (cpu_address == 16'hC07D) capture_status",
                "                else if (display_switch) capture_status <= 8'h08;\n"
                "                else if (cpu_address == 16'hC07D) capture_status")
    card.write_text(text, encoding='ascii')
    qip = BASE / 'card_platform.qip'
    closure = [Path(name) for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"', qip.read_text())]
    assert len(closure) == 12 and all(path.is_file() for path in closure)
    substitutions = {path.name: path for path in outputs}
    closure = [substitutions.get(path.name, path) for path in closure]
    return closure


if __name__ == '__main__':
    prepare()
