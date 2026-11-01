#!/usr/bin/env python3
"""Compose independent CPU pin sampling with the paced native-memory candidate."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = ROOT / 'fixtures/experiments/card-paced-system'
spec = importlib.util.spec_from_file_location('paced_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
BASE = parent.BASE
WORK = ROOT / 'local/experiments/card-sampled-system'
once = parent.once
sha = parent.sha


def prepare():
    # Redirect generation so the prior candidate remains frozen.
    parent.WORK = WORK
    closure, manifest, inputs = parent.prepare()
    source = WORK / 'card_irq_candidate.sv'
    text = once(source.read_text(), '.complete(cpu_ready), .due(pace_due)',
                '.complete(pace_due), .due(pace_due)')
    text = once(text, '.clk(clk), .reset(!por_n || !cpu_running), .ready(cpu_ready),',
                '.clk(clk), .reset(!por_n || !cpu_running), .sample_tick(pace_due), .ready(cpu_ready),')
    source.write_text(text, encoding='ascii')
    processor = next(path for path in closure if path.name == 'card_irq_cpu_bus.sv')
    text = once(processor.read_text(), '    input wire ready,',
                '    input wire sample_tick,\n    input wire ready,')
    text = once(text, '    // WAI wakeup needs an independent CPU tick policy before integration.\n'
                '    assign halted = waiting || stopped;',
                '    // WAI samples interrupt pins without issuing a bus request.\n'
                '    assign halted = stopped;')
    text = once(text, '.ce(complete)', '.ce(sample_tick)')
    text = once(text, '.rdy(1\'b1)', '.rdy(waiting || ready)')
    generated = WORK / processor.name
    generated.write_text(text, encoding='ascii')
    closure = [generated if path == processor else path for path in closure]
    return closure, manifest, inputs + [processor, Path(__file__), PARENT / 'prepare.py', PARENT / 'run.py']


if __name__ == '__main__':
    prepare()
