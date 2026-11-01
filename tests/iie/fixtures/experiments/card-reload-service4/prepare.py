#!/usr/bin/env python3
"""Continue the installed reload callback through live service 4."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-reload-service4'
PARENT = ROOT / 'fixtures/experiments/card-reload-callback'
spec = importlib.util.spec_from_file_location('callback_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
sha, once = parent.sha, parent.once


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    pins_path = ROOT / 'fixtures/experiments/card-service4-render/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    render = ROOT / 'local/experiments/card-service4-render'
    bench_source = render / 'tb_cache.sv'
    card_source = render / 'card_irq_candidate.sv'
    registers_source = ROOT / 'local/experiments/card-display-mask/card_irq_host_registers.sv'
    for path in (bench_source, card_source, registers_source):
        assert sha(path) == pins[str(path)], 'changed service4 source: ' + str(path)
    replacements = {}
    for path in (card_source, registers_source):
        target = WORK / path.name
        target.write_text(path.read_text(), encoding='ascii')
        replacements[path.name] = target
    sources = [replacements.get(path.name, path) for path in sources]
    bench = sources[0]
    text = once(bench.read_text(), '        reload_cpu = int\'(cpu_completed);',
        "        transact(1, 0, 33, 40, 0);\n        reload_cpu = int'(cpu_completed);")
    tail = bench_source.read_text()
    tail = tail[tail.index("        wait(capture_valid && capture_address == 16'hC07D && capture_data == 4);"):]
    tail = once(tail, 'bridge_index = 8; bridge_index <= 16;',
        'bridge_index = 12; bridge_index <= 20;')
    tail = once(tail, 'PASS service4 rendered fast=', 'PASS reload service4 fast=')
    text = text[:text.index('        wait(boundary);')] + tail
    bench.write_text(text, encoding='ascii')

    bridge_source = PARENT / 'bridge.lua'
    bridge = once(bridge_source.read_text(), 'sequence <= 11', 'sequence <= 20')
    bridge_path = WORK / 'bridge.lua'
    bridge_path.write_text(bridge, encoding='ascii')
    host_source = PARENT / 'execute.lua'
    host = once(host_source.read_text(),
        "dofile('fixtures/experiments/card-reload-callback/bridge.lua')",
        "dofile('local/experiments/card-reload-service4/bridge.lua')")
    host = once(host, 'local ack = false', 'local acks = 0')
    host = once(host, 'off == 1 or off == 12 or off == 13',
        'off == 1 or off == 12 or off == 13 or off == 33')
    host = once(host, 'and not ack,', 'and acks < 2,')
    host = once(host, '''            bridge(true, 12, 0)
            ack = true
            space:write_u8(0x310024, 1)''', '''            acks = acks + 1
            if acks == 2 then
                local function snapshot(name, address, size)
                    local file = assert(io.open(run .. '/' .. name, 'wb'))
                    file:write(space:read_range(address, address + size - 1, 8))
                    file:close()
                end
                snapshot('service4-world.bin', world - 0x5960, 0x5c49)
                snapshot('service4-frame.bin', 0x100000 - 64, frame_size + 128)
                snapshot('service4-code.bin', 0x200000, driver == 5 and 0xa442 or 0x75d6)
                snapshot('service4-main.bin', 0x280000, 0x685c)
                snapshot('service4-converted.bin', 0x370000, 0x4080)
            end
            bridge(true, 12, 0)
            space:write_u8(0x310024, acks)''')
    host = once(host,
        "        .. 'save \"' .. run .. '/service-state.bin\",310000,10; trace off,:maincpu; quit')",
        """        .. 'save "' .. run .. '/service-state.bin",310000,10; g')
    cpu.debug:bpset(0x20281c, 'b@310024==2',
        'save "' .. run .. '/final-world.bin",2fa6a0,5c49; '
        .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
        .. 'save "' .. run .. '/final-state.bin",310000,10; trace off,:maincpu; quit')
    if os.getenv('IIE_BAD_CACHE') == '1' then
        cpu.debug:bpset(0x200a7e, 'b@310024==1',
            'save "' .. run .. '/bad-cache-before.bin",2fbc8e,2; '
            .. 'b@(a5-4371)=b@(a5-4371)^1; '
            .. 'save "' .. run .. '/bad-cache-after.bin",2fbc8e,2; g')
    end""")
    host_path = WORK / 'execute.lua'
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', pins_path, bench_source,
        card_source, registers_source, bridge_source, host_source, bridge_path, host_path]


if __name__ == '__main__':
    prepare()
