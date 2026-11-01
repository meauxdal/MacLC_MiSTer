#!/usr/bin/env python3
"""Add host mask readback and execute the original mask setup prefix."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-mask'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare():
    pins_path = ROOT / 'fixtures/experiments/card-runtime-bridge/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, 'changed bridge input: ' + name
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [Path(name) for name in names[names.index(str(binding)):] if Path(name).suffix in ('.sv', '.v')]
    WORK.mkdir(parents=True, exist_ok=True)
    original = ROOT / 'local/experiments/card-runtime-bridge/tb_bridge.sv'
    sources = [path for path in sources if path != original]
    text = once(original.read_text(), '        bridge_active = 1;', '''        if (!$value$plusargs("mask=%d", mask_seed)) mask_seed = 252;
        transact(1, 0, 33, mask_seed, 0);
        bridge_active = 1;''')
    text = once(text, '    integer bridge_fields, bridge_index;', '    integer bridge_fields, bridge_index, mask_seed;')
    text = once(text, 'bridge_index <= 5;', 'bridge_index <= 7;')
    text = once(text, '        bridge_active = 0;',
                '        bridge_active = 0;\n        transact(0, 0, 33, (mask_seed & 3) | 32, 0);')
    bench = WORK / 'tb_mask.sv'
    bench.write_text(text, encoding='ascii')
    registers = ROOT / 'local/experiments/card-softswitch/card_irq_host_registers.sv'
    text = once(registers.read_text(), '    reg [7:0] command_byte;',
                '    reg [7:0] command_byte, host_mask;')
    text = once(text, '            command_byte <= 0;', '            command_byte <= 0;\n            host_mask <= 0;')
    text = once(text, "                                {1'b0, 6'h0C}, {1'b0, 6'h18}, {1'b0, 6'h19},\n                                {1'b0, 6'h21}: ;",
                "                                {1'b0, 6'h0C}, {1'b0, 6'h18}, {1'b0, 6'h19}: ;\n"
                "                                {1'b0, 6'h21}: host_mask <= req_wdata[7:0];")
    text = once(text, "                                {1'b0, 6'h20}: rsp_rdata <= {8'b0, command_byte};",
                "                                {1'b0, 6'h20}: rsp_rdata <= {8'b0, command_byte};\n"
                "                                {1'b0, 6'h21}: rsp_rdata <= {8'b0, host_mask};")
    candidate = WORK / registers.name
    candidate.write_text(text, encoding='ascii')
    sources = [candidate if path == registers else path for path in sources]
    host_source = ROOT / 'local/experiments/card-runtime-bridge/execute.lua'
    host = once(host_source.read_text(), "        cpu.state['PC'].value = base + 0x281c", """        cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')
        cpu.state['A4'].value = card
        cpu.state['PC'].value = base + 0x2c4""")
    host = once(host, "            assert(offset - card == 0xc and mask == 0xff000000 and (data >> 24) == 0, 'Unexpected write')", """            if offset - card == 0x20 and mask == 0x00ff0000 then
                local value = (data >> 16) & 0xff
                bridge(true, 8, 0x21, value)
                bus:write(string.format('[true,8,33,%d]\\n', value))
                return
            end
            assert(offset - card == 0xc and mask == 0xff000000 and (data >> 24) == 0, 'Unexpected write')""")
    host = once(host, "dofile('fixtures/experiments/card-runtime-bridge/bridge.lua')",
                "dofile('fixtures/experiments/card-display-mask/bridge.lua')")
    (WORK / 'execute.lua').write_text(host, encoding='ascii')
    image = ROOT / 'local/experiments/card-monitor-resume/initial.hex'
    return [bench, *sources], image, [pins_path, original, registers, host_source, image, HERE / 'prepare.py',
                                    HERE / 'bridge.lua', WORK / 'execute.lua']
