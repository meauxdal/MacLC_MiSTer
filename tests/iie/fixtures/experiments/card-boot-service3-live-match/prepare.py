#!/usr/bin/env python3
"""Compose the matching BS3 handler with the monitor's external scan."""
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-boot-service3-live-match'
PARENT = HERE.parent / 'card-boot-service2'
BASE = HERE.parent / 'card-boot-service3'
EXTERNAL = HERE.parent / 'card-external-cx'
spec = importlib.util.spec_from_file_location('matching_prepare', EXTERNAL / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    os.environ['IIE_CX_CONTROL'] = '0'
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    pins_path = HERE.parent / 'card-boot-service3-contract/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    metadata = ROOT / 'local/experiments/firmware-memory/resources.json'
    fork = ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc'
    for path in (metadata, fork):
        assert sha(path) == pins[str(path)], str(path)
    entry = next(item for item in json.loads(metadata.read_text())['resources']
                 if (item['type'], item['id']) == ('STR ', 0x5101))
    resource = fork.read_bytes()[entry['fork_offset']:entry['fork_offset'] + entry['size']]
    payload = WORK / 'str5101.bin'
    payload.write_bytes(resource)
    assert len(resource) == 77 and resource[0] == 76 and sha(payload) == entry['sha256']
    card = WORK / 'card_irq_candidate.sv'
    text = once(card.read_text(), "service_returns == 4 && cpu_valid && cpu_sync && cpu_address == 16'hFAC0;",
                "service_returns == 5 && cpu_valid && cpu_sync && cpu_address == 16'hFA9B;")
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    for counter in ('host_returns', 'register_reads'):
        text = once(text, f"if ({counter} >= 15 && register_index == 3) return_value = return_value & 8'hFD;",
                    f"if ({counter} >= 15 && {counter} < 20 && register_index == 3) return_value = return_value & 8'hFD;\n"
                    f"                if ({counter} >= 20 && register_index == 3) return_value = return_value | 8'h02;")
    text = once(text, "(card_cpu_address == 16'hFAC2 && register_reads == 20 && rti_contexts == 3)",
                "(card_cpu_address == 16'hFAC2 && register_reads == 20 && rti_contexts == 3) ||\n"
                "             (card_cpu_address == 16'hFAC2 && register_reads == 25 && rti_contexts == 4)")
    text = once(text, "(rti_contexts == 3 ? saved_p & 8'hFD : saved_p)",
                "(rti_contexts == 3 ? saved_p & 8'hFD : rti_contexts == 4 ? saved_p | 8'h02 : saved_p)")
    text = once(text, "card_cpu_address !== 16'hFAC0 || opcodes != 4 || rtis != 4 || nmis != 4",
                "card_cpu_address !== 16'hFA9B || opcodes != 5 || rtis != 5 || nmis != 5")
    text = once(text, 'register_writes != 20 || register_reads != 20 || service_writes != 20',
                'register_writes != 25 || register_reads != 25 || service_writes != 25')
    text = once(text, 'host_returns != 20 || switch_services != 5 || rti_contexts != 4',
                'host_returns != 25 || switch_services != 5 || rti_contexts != 5')
    text = once(text, 'capture_count != switch_services + 45', 'capture_count != switch_services + 56')
    text = once(text, 'PASS external-cx fast=', 'PASS matching-bs3 fast=')
    bench.write_text(text, encoding='ascii')
    host = WORK / 'host.lua'
    text = host.read_text()
    text = once(text, '        local function record(write, width, offset, value)',
                (HERE / 'resource.lua').read_text() + '\n        local function record(write, width, offset, value)')
    text = text.replace('return_writes == 20', 'return_writes == 25')
    text = text.replace('return_writes <= 20', 'return_writes <= 25')
    text = text.replace('service_acks <= 4', 'service_acks <= 5')
    text = once(text, "                        snapshot('bs3-preack-code.bin', base, #bytes)", """                        snapshot('bs3-preack-code.bin', base, #bytes)
                    elseif service_acks == 5 then
                        assert(space:read_u8(world - 0x88f) == 3, 'Expected matching service 3')
                        snapshot('match-world.bin', world - 0x5960, 0x5c49)
                        snapshot('match-code.bin', base, #bytes)
                        snapshot('match-frame.bin', 0x100000 - 64, frame_size + 128)
                        snapshot('resource-after.bin', 0x3600c0, 206)
""")
    start = text.index("        if os.getenv('IIE_WRONG_BOOT_P')")
    end = text.index("        cpu.debug:bpset(base + 0x1cae", start)
    text = text[:start] + text[end:]
    text = once(text, "'temp0=0'", "'temp0=0; temp1=0; temp2=0; temp3=0'")
    text = once(text, "'b@(a5-88f)==3', 'temp0=1; g'", "'b@(a5-88f)==3', 'temp0=temp0+1; g'")
    text = once(text, "'temp0==1', 'temp0=2; g'", "'temp0==2', 'temp0=3; g'")
    text = once(text, "base + 0x281c, 'temp0==2'", "base + 0x281c, 'temp0==3'")
    host.write_text(text, encoding='ascii')
    return sources, image, inputs + [pins_path, metadata, fork, payload, EXTERNAL / 'prepare.py',
        HERE / 'prepare.py', HERE / 'resource.lua', HERE / 'checks.py', host]
