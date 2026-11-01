#!/usr/bin/env python3
"""Generate a paced variant without rewriting frozen experiment outputs."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'local/experiments/card-softswitch'
WORK = ROOT / 'local/experiments/card-paced-system'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    manifest_path = ROOT / 'fixtures/experiments/card-softswitch/results.json'
    manifest = json.loads(manifest_path.read_text())
    qip = ROOT / 'local/experiments/maclc-iie-banking-build/card_platform.qip'
    closure = [Path(name) for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"', qip.read_text())]
    assert len(closure) == 12
    for index, path in enumerate(closure):
        generated = BASE / path.name
        if generated.is_file():
            closure[index] = generated
    for path in closure:
        assert sha(path) == manifest['inputs_sha256'][str(path)], 'changed frozen source: ' + str(path)
    WORK.mkdir(parents=True, exist_ok=True)
    source = BASE / 'card_irq_candidate.sv'
    text = once(source.read_text(), 'parameter SUPPRESS_NMI = 0,',
                'parameter PACE_FAST = 0, PACE_CLOCK_HZ = 32500000,\n'
                '                            SUPPRESS_NMI = 0,')
    text = once(text, '    wire cpu_ready;', '''    wire cpu_ready, pace_due;
    card_cycle_pacer #(.CLOCK_HZ(PACE_CLOCK_HZ)) pace (
        .clk(clk), .reset(!por_n || !cpu_running), .fast(1'(PACE_FAST)),
        .complete(cpu_ready), .due(pace_due)
    );''')
    text = once(text, 'assign master_rsp_ready[1] = cpu_memory_wait;',
                'assign master_rsp_ready[1] = cpu_memory_wait && pace_due && runnable && released;')
    text = once(text, 'assign cpu_ready = runnable && released &&',
                'assign cpu_ready = runnable && released && pace_due &&')
    text = once(text, 'wire opcode02_complete = runnable && cpu_sync && !cpu_write &&',
                'wire opcode02_complete = cpu_ready && cpu_sync && !cpu_write &&')
    generated = WORK / source.name
    generated.write_text(text, encoding='ascii')
    closure = [generated if path == source else path for path in closure]
    pacer = ROOT / 'fixtures/experiments/card-cpu-pacing/card_cycle_pacer.sv'
    pacer_manifest = json.loads((ROOT / 'fixtures/experiments/card-cpu-pacing/results.json').read_text())
    assert sha(pacer) == pacer_manifest['inputs_sha256'][str(pacer.relative_to(ROOT))]
    closure.append(pacer)
    return closure, manifest, [manifest_path, qip, source, pacer]


if __name__ == '__main__':
    prepare()
