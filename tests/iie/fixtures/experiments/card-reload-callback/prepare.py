#!/usr/bin/env python3
"""Bind settings reload transactions before the original live service-1 ACK."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-reload-callback'
PARENT = ROOT / 'fixtures/experiments/card-runtime-bridge'
spec = importlib.util.spec_from_file_location('runtime_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
sha, once = parent.sha, parent.once


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    bench = sources[0]
    text = once(bench.read_text(), '    reg bridge_active = 0;',
        '    integer reload_cpu, reload_captures;\n    reg bridge_active = 0;')
    text = once(text, '        bridge_active = 1;', '''        transact(1, 0, 13, 161, 0);
        reload_cpu = int'(cpu_completed);
        reload_captures = int'(capture_count);
        bridge_active = 1;''')
    text = once(text, 'bridge_index <= 5;', 'bridge_index <= 11;')
    marker = '            $display("REPLY %0d %0d", bridge_sequence, bridge_reply);'
    text = once(text, marker, '''            if (bridge_index <= 10 &&
                (!capture_valid || capture_address != 16'hC07D || capture_data != 1 ||
                 capture_status != 8'hE0 || cpu_completed != 32'(reload_cpu) ||
                 capture_count != 32'(reload_captures)))
                $fatal(1, "reload disturbed pending service");
''' + marker)
    bench.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', PARENT / 'prepare.py']
