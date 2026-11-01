#!/usr/bin/env python3
"""Call the original monitor keyboard polling routine from a bounded caller."""
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-keyboard-monitor'
PARENT = HERE.parent / 'card-keyboard-arrival'
spec = importlib.util.spec_from_file_location('arrival_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    payload = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    firmware = payload.read_bytes()
    routine = bytes.fromhex('e64ed002e64fad00c010f58d10c060')
    assert firmware[0x83b:0x84a] == routine
    ledger = WORK / 'consumer-overlay.json'
    old = json.loads(ledger.read_text())
    base_image = next(path for path in inputs if path != image and sha(path) == old['base_image_sha256'])
    original = bytes(int(value, 16) for value in base_image.read_text().split())
    address = 0x23b65
    caller = bytes.fromhex('8d07c0 203bc8 8d0002 ad00c0 8d0102 8d06c0 4c65fb')
    patched = bytearray(original)
    patched[address:address + len(caller)] = caller
    assert patched[0x2083b:0x2084a] == routine
    image.write_text(''.join(f'{value:02x}\n' for value in patched), encoding='ascii')
    ledger.write_text(json.dumps({'physical_address': address, 'cpu_address': 0xfb65,
        'original': original[address:address + len(caller)].hex(), 'caller': caller.hex(),
        'routine_cpu_address': 0xc83b, 'routine': routine.hex(),
        'firmware_sha256': sha(payload), 'base_image_sha256': sha(base_image),
        'consumer_image_sha256': sha(image)}, indent=2) + '\n', encoding='ascii')
    bench = sources[0]
    text = once(bench.read_text(), '    task consume_key(input [7:0] key);',
        '    reg [15:0] seed_before;\n    reg rom_before;\n    task consume_key(input [7:0] key);')
    text = once(text, '            consumer_reads = 0; consumer_clears = 0; consumed_key = key;',
        '''            seed_before = {expected['h4F], expected['h4E]};
            rom_before = dut.platform.card.card.internal_rom;
            if (rom_before) $fatal(1, "unexpected caller ROM context");
            consumer_reads = 0; consumer_clears = 0; consumed_key = key;''')
    text = once(text, '            saved_a = dut.platform.card.card.processor.cpu.reg_a;\n            saved_p = dut.platform.card.card.processor.cpu.reg_p;\n            $fflush(instructions);',
        '''            if ({expected['h4F], expected['h4E]} !== seed_before + 16'd1 ||
                dut.platform.card.card.internal_rom !== rom_before)
                $fatal(1, "original input seed/ROM mismatch");
            saved_a = dut.platform.card.card.processor.cpu.reg_a;
            saved_p = dut.platform.card.card.processor.cpu.reg_p;
            $fflush(instructions);''')
    if os.getenv('IIE_DEFERRED_KEY') == '1':
        text = once(text, 'bridge_index <= 111;', 'bridge_index <= 112;')
        text = once(text, '                consume_key(bridge_value[7:0] | 8\'h80);',
                    '                if (event_writes == 2) consume_key(bridge_value[7:0] | 8\'h80);')
        text = once(text, "            if (bridge_index == 70) consume_key(8'hD5);",
                    "            if (bridge_index == 70) consume_key(8'hD5);\n            if (bridge_index == 106) consume_key(8'hC1);")
    bench.write_text(text, encoding='ascii')
    host = WORK / 'execute.lua'
    lua = once(host.read_text(), 'local/experiments/card-keyboard-arrival/bridge.lua',
               'local/experiments/card-keyboard-monitor/bridge.lua')
    if os.getenv('IIE_DEFERRED_KEY') == '1':
        lua = once(lua, 'trace off,:maincpu; quit',
            "d@3efffc=290800; a7=3efffc; a4=e00000; pc=202480; g")
        marker = "    if os.getenv('IIE_BAD_BUSY') == '1' then"
        lua = once(lua, marker, '''    cpu.debug:bpset(0x290800, '1',
        'save "' .. run .. '/deferred-world.bin",2fa6a0,5c49; '
        .. 'save "' .. run .. '/deferred-code.bin",200000,' .. (driver == 5 and 'a442' or '75d6') .. '; '
        .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a4; '
        .. 'save "' .. run .. '/deferred-state.bin",310000,10; trace off,:maincpu; quit')
''' + marker)
        bridge = WORK / 'bridge.lua'
        bridge.write_text(once(bridge.read_text(), 'sequence <= 111', 'sequence <= 112'), encoding='ascii')
    host.write_text(lua, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', PARENT / 'prepare.py']
