#!/usr/bin/env python3
"""Recover the original service-4 cache-transfer boundary."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    pins = json.loads((ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json').read_text())['inputs_sha256']
    windows = {
        0x1CC4: '4efa01f6',
        0x1EBC: '45faff56323c00a7224a10110000008012c051c9fff6343c00a87600363c06504ebae6a01b7c0009f76e4e75',
        0x057E: '7e002803d8425384286dedca08030010670a082c00030021670000e8',
        0x059A: '082c000500216768',
        0x05EA: '41f53320afee08030010670641f533209fee5346700110c010db51cefffa7e01',
        0x060A: '082c0004002167680c4408006500014e',
        0x0766: '4a476708426df6846100030e4e75',
    }
    inputs, drivers = [], []
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        assert sha(path) == pins[str(path.relative_to(ROOT))], 'changed original CODE'
        code = path.read_bytes()
        for offset, expected in windows.items():
            assert code[offset:offset + len(expected) // 2].hex() == expected, hex(offset)
        source = code[0x1E14:0x1EBC]
        transformed = bytes(value | 0x80 for value in source)
        count, destination = 0xA8, 0x650
        cache_offset = int.from_bytes(code[0x5EE:0x5F0], 'big', signed=True) + destination * 2
        assert len(source) == count and cache_offset == -0x4372
        assert destination + count - 1 < 0x7F8
        cache = bytes(value for item in transformed for value in (1, item))
        drivers.append({'driver': driver, 'source_sha256': hashlib.sha256(source).hexdigest(),
                        'transformed_sha256': hashlib.sha256(transformed).hexdigest(),
                        'cache_pairs_sha256': hashlib.sha256(cache).hexdigest()})
        inputs.append(path)
    registers = ROOT / 'local/experiments/card-softswitch/card_irq_host_registers.sv'
    bridge_pins = ROOT / 'fixtures/experiments/card-runtime-bridge/results.json'
    assert sha(registers) == json.loads(bridge_pins.read_text())['inputs_sha256'][str(registers)]
    text = registers.read_text()
    reads = text.split('case ({req_word, req_offset})')[2].split('endcase')[0]
    assert "6'h21" not in reads and 'rsp_error <= 1' in reads
    inputs += [registers, bridge_pins, Path(__file__), ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json']
    result = {
        'scope': 'static original-byte contract; no service4 execution or rendering',
        'windows': {f'{offset:04X}': value for offset, value in windows.items()},
        'drivers': drivers,
        'transfer': {'source_resource_range': '1E14-1EBB', 'count': 168,
                     'logical_destination_range': '0650-06F7',
                     'main_cache_A5_relative_range': '-4372..-4223',
                     'cache_format': 'dirty byte 01, transformed source byte',
                     'first_host_read': {'offset': '21', 'width': 8, 'tested_bit': 5},
                     'renderer_entry': '0A7E', 'post_transfer_A5_minus_0892': 9},
        'current_RTL_boundary': 'byte read +21 is unsupported; no status value supplied',
        'inputs_sha256': {str(path): sha(path) for path in inputs},
    }
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS original CODE5/6 service4 cache contract; RTL +21 read remains unsupported')


if __name__ == '__main__':
    main()
