#!/usr/bin/env python3
"""Continue live original dispatch to the service-4 renderer boundary."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-service4-cache'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare():
    pins_path = ROOT / 'fixtures/experiments/card-display-mask/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, 'changed mask input: ' + name
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [Path(name) for name in names[names.index(str(binding)):] if Path(name).suffix in ('.sv', '.v')]
    WORK.mkdir(parents=True, exist_ok=True)
    original = ROOT / 'local/experiments/card-display-mask/tb_mask.sv'
    text = original.read_text()
    loop_start = '        for (bridge_index = 1; bridge_index <= 7; bridge_index = bridge_index + 1) begin'
    loop = text[text.index(loop_start):text.index('        bridge_active = 0;')]
    second = loop.replace('bridge_index = 1; bridge_index <= 7;', 'bridge_index = 8; bridge_index <= 15;')
    text = once(text, '        wait(boundary);', '        wait(boundary);\n        bridge_active = 1;\n' + second + '        bridge_active = 0;')
    text = once(text, "        if (card_cpu_address != 16'hFB63 || opcodes != 1 || rtis != 1 ||",
                "        if (card_cpu_address != 16'hC07D || opcodes != 2 || rtis != 1 ||\n"
                "            capture_status != 8'hE0 || capture_data != 4 || nmis != 2 || service_writes != 10 ||")
    text = once(text, 'capture_count != switch_services + 2 || capture_valid ||',
                'capture_count != switch_services + 3 || !capture_valid ||')
    text = once(text, 'PASS monitor fast=', 'PASS service4 held fast=')
    bench = WORK / 'tb_cache.sv'
    bench.write_text(text, encoding='ascii')
    card = ROOT / 'local/experiments/card-monitor-resume/card_irq_candidate.sv'
    candidate = WORK / card.name
    candidate.write_text(once(card.read_text(),
        "assign boundary = monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFB63;",
        "assign boundary = capture_valid && capture_address == 16'hC07D && capture_data == 4;"), encoding='ascii')
    sources = [candidate if path == card else path for path in sources]
    host_source = ROOT / 'local/experiments/card-display-mask/execute.lua'
    host = once(host_source.read_text(), "dofile('fixtures/experiments/card-display-mask/bridge.lua')",
                "dofile('fixtures/experiments/card-service4-cache/bridge.lua')")
    host = once(host, "local bus = assert(io.open(run .. '/bus.jsonl', 'w'))",
                "local bus = assert(io.open(run .. '/bus.jsonl', 'w'))\nbus:setvbuf('no')")
    host = once(host, '        space:write_u8(0x260, 0)',
                '        space:write_u8(0x260, 0)\n        space:write_u16(world - 0x97c, 0x5a5a)')
    host = once(host, "            if ack then\n                assert(off == 1 and count == 1, 'Unexpected post-ACK read')\n            else\n                result = bridge(false, count * 8, off, 0)\n            end",
                '            result = bridge(false, count * 8, off, 0)')
    host = once(host, "        cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')", """        cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')
        cpu.debug:bpset(base + 0xa7e, '1',
            'save "' .. run .. '/world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'printf "RENDER_BOUNDARY pc=%08X sp=%08X",pc,a7; trace off,:maincpu; quit')""")
    host = once(host, '    elseif frames == 3001 then', """    elseif frames == 3001 then
        local boundary = assert(io.open(run .. '/world.bin', 'rb'), 'Renderer boundary not reached')
        boundary:close()""")
    (WORK / 'execute.lua').write_text(host, encoding='ascii')
    image = ROOT / 'local/experiments/card-monitor-resume/initial.hex'
    return [bench, *sources], image, [pins_path, original, card, host_source, image, HERE / 'prepare.py',
                                    HERE / 'bridge.lua', WORK / 'execute.lua']
