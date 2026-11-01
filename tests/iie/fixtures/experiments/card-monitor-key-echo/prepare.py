#!/usr/bin/env python3
"""Continue the original input path beyond service 6."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY = HERE.parent / 'card-monitor-key-input'
WORK = HERE.parents[2] / 'local/experiments/card-monitor-key-echo'
spec = importlib.util.spec_from_file_location('echo_key_prepare', KEY / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha
PROMPT, POST, MATCH = parent.PROMPT, parent.POST, parent.MATCH
ROOT, BASE, PARENT = parent.ROOT, parent.BASE, parent.PARENT


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    card = WORK / 'card_irq_candidate.sv'
    text = card.read_text()
    text = once(text, 'reg test_release_idle = 0;', 'reg test_release_idle = 0;\n    reg test_release_key = 0;')
    text = once(text, "(service_returns == 6 && cpu_address == 16'hFD7A)",
                "(service_returns == 6 && ((!test_release_key && cpu_address == 16'hFD7A) ||\n"
                "          (test_release_key && cpu_address == 16'hC267)))")
    text = once(text, 'wire protected_write =', '''wire protected_write =
        (test_release_key && cpu_write && (($test$plusargs("drop_buffer") && cpu_address == 16'h0200) ||
         ($test$plusargs("drop_echo") && cpu_address == 16'h0501))) ||''')
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    text = once(text, '        check_key();\n        $display("EXCHANGE', '''        check_key();
        for (integer offset = 0; offset < 256; offset = offset + 1) input_buffer[offset] = backing('h200 + offset);
        $fclose(instructions);
        instructions = $fopen(echo_instruction_path, "w");
        if (instructions == 0) $fatal(1, "echo trace open failed");
        dut.platform.card.card.test_release_key = 1;
        #1;
        wait(boundary);
        @(negedge clk_sys);
        check_echo();
        $display("EXCHANGE''')
    text = once(text, '    integer raw_key =', (HERE / 'echo.sv').read_text() + '\n    integer raw_key =')
    text = once(text, '    integer raw_key =', '    reg [1023:0] echo_instruction_path;\n    integer raw_key =')
    text = once(text, '        $readmemh(image_path, expected);', '''        if (!$value$plusargs("echo_instructions=%s", echo_instruction_path)) $fatal(1, "missing echo trace");
        $readmemh(image_path, expected);''')
    text = once(text, 'PASS key-input fast=', 'PASS key-echo fast=')
    text = once(text, 'if (key_injected && cpu_ready)',
                'if (key_injected && !dut.platform.card.card.test_release_key && cpu_ready)')
    bench.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'run.py', HERE / 'checks.py', HERE / 'echo.sv', KEY / 'run.py']

