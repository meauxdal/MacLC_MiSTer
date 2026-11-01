#!/usr/bin/env python3
"""Generate a deferred-reset variant of the sampled native-memory candidate."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SAMPLED = ROOT / 'fixtures/experiments/card-sampled-system'
spec = importlib.util.spec_from_file_location('sampled_prepare', SAMPLED / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
BASE_WORK = parent.WORK
BASE = parent.BASE
WORK = ROOT / 'local/experiments/card-reset-system'
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    closure, manifest, inputs = parent.prepare()
    pins_path = SAMPLED / 'results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for path in closure:
        original = BASE_WORK / path.name if path.parent == WORK else path
        assert sha(path) == pins[str(original)], 'changed sampled input: ' + str(original)
    source = WORK / 'card_irq_candidate.sv'
    text = once(source.read_text(), '    reg cpu_running, start_pending, armed, report_mode;', '''    reg cpu_running, start_pending, armed, report_mode;
    reg reset_pending, reset_restart;
    wire reset_command = command_write && ((sidefx_word && sidefx_wdata == 16'h0802) ||
        (!sidefx_word && sidefx_wdata[7:0] == 8'h80 && reset_mask == 8'hFC));
    wire reset_stopping = reset_pending || reset_command;
    wire reset_commit = reset_pending && drained && !cpu_memory_wait;''')
    text = once(text, '&& !fault && !unsupported_cpu;',
                '&& !fault && !unsupported_cpu &&\n                    (!reset_stopping || cpu_memory_wait);')
    text = once(text, 'assign req_ready = host_ready && !hold_ack;',
                'assign req_ready = host_ready && !hold_ack && !reset_stopping;')
    text = once(text, '.req_valid(req_valid && !hold_ack)',
                '.req_valid(req_valid && !hold_ack && !reset_stopping)')
    text = once(text, '&& !protected_write && !cpu_memory_wait;',
                '&& !protected_write && !cpu_memory_wait && !reset_stopping;')
    text = once(text, 'if (start_pending && drained && !cpu_memory_wait)',
                'if (start_pending && drained && !cpu_memory_wait && !reset_stopping)')
    text = once(text, '            cpu_running <= 0;\n            start_pending <= 0;',
                '            cpu_running <= 0;\n            start_pending <= 0;\n'
                '            reset_pending <= 0;\n            reset_restart <= 0;')
    begin = text.index('                if ((sidefx_word && sidefx_wdata ==')
    end = text.index("                end else if (!sidefx_word && (sidefx_wdata[7:0] &", begin)
    old = text[begin:end]
    text = once(text, old, '''                if (reset_command) begin
                    reset_pending <= 1;
                    reset_restart <= !sidefx_word;
''')
    end = '''                end else if (cpu_running && (ack || read_release)) fault <= 1;
            end'''
    text = once(text, end, end + '''
            // Accepted memory work completes before CPU and capture state reset.
            if (reset_commit) begin
                reset_pending <= 0;
                nmi_pending <= 0;
                nmi_overlay <= 0;
                irq_level <= 0;
                nmi_delay_left <= 0;
                irq_delay_left <= 0;
                cpu_running <= 0;
                start_pending <= reset_restart;
                armed <= 0;
                report_mode <= 0;
                capture_valid <= 0;
                permitted <= 0;
                keyboard <= 0;
                display_switches <= 0;
            end''')
    source.write_text(text, encoding='ascii')
    return closure, manifest, inputs + [Path(__file__), SAMPLED / 'prepare.py', pins_path]


if __name__ == '__main__':
    prepare()
