#!/usr/bin/env python3
"""Check original saved-register exchange and service-4 banner count."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-saved-register-return'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(data, offset, expected):
    assert data[offset:offset + len(expected) // 2].hex() == expected, hex(offset)


def jump(data, offset):
    check(data, offset, '4efa')
    return offset + 2 + int.from_bytes(data[offset + 2:offset + 4], 'big', signed=True)


def banner(memory, y):
    stores = []
    while True:
        source = (0xff09 + y) & 0xffff
        stores.append({'y': y, 'source': source, 'destination': 0x40e + y,
                       'data': memory[source - 0xc000] if source >= 0xc000 else None})
        y = (y - 1) & 255
        if y == 0:
            return stores


def main():
    dispatch_pins_path = ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json'
    monitor_pins_path = ROOT / 'fixtures/experiments/card-monitor-entry/results-1.json'
    dispatch_pins = json.loads(dispatch_pins_path.read_text())['inputs_sha256']
    monitor_pins = json.loads(monitor_pins_path.read_text())['inputs_sha256']
    firmware = ROOT / 'local/experiments/firmware-memory/decoded'
    monitor_path = firmware / 'Monx_2606.payload.bin'
    receiver_path = firmware / 'Monx_2607.payload.bin'
    for path in (monitor_path, receiver_path):
        assert sha(path) == monitor_pins[str(path)], str(path)
    monitor, receiver = monitor_path.read_bytes(), receiver_path.read_bytes()
    receiver_windows = {
        0x1c: '8d78c08e79c08c7ac0ba8e7cc0bd01018d7bc0',
        0x52: 'ae7cc09aad7bc09d0101ac7ac0ae79c0ad78c040',
    }
    for offset, expected in receiver_windows.items():
        check(receiver, offset, expected)
    monitor_windows = {0x3b60: '2058fc0204b909ff990e0488d0f760',
                       0x3f0a: 'c1f0f0ece5a0afafe5'}
    for offset, expected in monitor_windows.items():
        check(monitor, offset, expected)
    windows = {0x135e: '322c00040241007f4ebb141a',
               0x17ba: '322c00040241007f4ebb141a',
               0x1c9a: '7000102c000c1b40f7710c00000864044ebb0408422c000c4e75',
               0x1cc4: '4efa01f6',
               0x1ebc: '45faff56323c00a7224a10110000008012c051c9fff6343c00a87600363c06504ebae6a0',
               0x1ee0: '1b7c0009f76e4e75'}
    mappings = []
    for index, name in enumerate(('A', 'X', 'Y', 'P', 'SP')):
        displacement = 0xf76c + index
        write_handler = 0x1c5e + index * 12
        read_handler = 0x1c2e + index * 8
        windows[write_handler] = f'1b6c000c{displacement:04x}422c000c4e75'
        windows[read_handler] = f'196d{displacement:04x}00194e75'
        mappings.append({'register': name, 'cpu_address': 0xc078 + index,
                         'a5_displacement': displacement - 0x10000,
                         'write_table': 0x1562 + index * 4, 'write_handler': write_handler,
                         'read_table': 0x19be + index * 4, 'read_handler': read_handler})
    inputs = [dispatch_pins_path, monitor_pins_path, monitor_path, receiver_path, HERE / 'analyze.py']
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        assert sha(path) == dispatch_pins[str(path.relative_to(ROOT))], str(path)
        code = path.read_bytes()
        for offset, expected in windows.items():
            check(code, offset, expected)
        assert jump(code, 0x1cc4) == 0x1ebc
        for item in mappings:
            assert item['write_table'] == 0x1382 + (item['cpu_address'] & 127) * 4
            assert item['read_table'] == 0x17de + (item['cpu_address'] & 127) * 4
            assert jump(code, item['write_table']) == item['write_handler']
            assert jump(code, item['read_table']) == item['read_handler']
        inputs.append(path)
    candidate = ROOT / 'fixtures/experiments/card-monitor-entry/prepare.py'
    text = candidate.read_text()
    assert 'if (cpu_write && service_register) service_regs[cpu_address[2:0]] <= cpu_wdata;' in text
    assert 'cpu_rdata = service_regs[cpu_address[2:0]];' in text
    inputs.append(candidate)
    stores = banner(monitor, 9)
    assert len(stores) == 9
    assert bytes(item['data'] for item in reversed(stores)) == bytes.fromhex('c1f0f0ece5a0afafe5')
    assert [item['destination'] for item in stores] == list(range(0x417, 0x40e, -1))
    zero, eight = banner(monitor, 0), banner(monitor, 8)
    assert len(zero) == 256 and len(eight) == 8
    assert zero != stores and eight != stores
    WORK.mkdir(parents=True, exist_ok=True)
    traces = WORK / 'banner-cases.json'
    traces.write_text(json.dumps({'saved_y_9': stores, 'saved_y_0': zero, 'saved_y_8': eight}, indent=2) + '\n', encoding='ascii')
    result = {'scope': 'static original-byte contract; no live register exchange',
              'mappings': mappings,
              'code_windows': {f'{offset:04X}': value for offset, value in windows.items()},
              'receiver_windows': {f'{0xd000 + offset:04X}': value for offset, value in receiver_windows.items()},
              'monitor_windows': {f'{0xc000 + offset:04X}': value for offset, value in monitor_windows.items()},
              'banner': {'saved_y': 9, 'stores': stores, 'text_low_7_bits': 'Apple //e'},
              'controls': {'saved_y_0_store_count': len(zero), 'saved_y_8_store_count': len(eight),
                           'result': 'both differ from original nine-byte banner'},
              'inputs_sha256': {str(path): sha(path) for path in inputs},
              'captures_sha256': {str(traces): sha(traces)}}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS CODE5/6 five-register exchange; service4 Y=9; zero/eight controls differ')


if __name__ == '__main__':
    main()
