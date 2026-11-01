#!/usr/bin/env python3
"""Check original dispatch targets and renderer initialization prerequisites."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jump(code, site):
    assert code[site:site + 2] == bytes.fromhex('4efa')
    return site + 2 + int.from_bytes(code[site + 2:site + 4], 'big', signed=True)


def main():
    pins_path = ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    checks = {0x00A6: '41edd7ee2b48ef9a41edc7ee2b48ef96',
              0x02A6: '426df68e426df68c', 0x0A7E: '082d0006f68c6632082d0005f68c6640'}
    inputs, drivers = [], []
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        assert sha(path) == pins[str(path.relative_to(ROOT))]
        code = path.read_bytes()
        variant = ({0x0AB2: '610038ac4e75', 0x4360: '226df7a2',
                    0x4080: '3c2df778', 0x4088: '24352520ef9e'} if driver == 5 else
                   {0x0AB2: '610036924e75', 0x4146: '226df7a2',
                    0x3F1E: '3c2df778', 0x3F26: 'e98ac4c6'})
        for site, expected in (checks | variant).items():
            assert code[site:site + len(expected) // 2].hex() == expected, hex(site)
        assert jump(code, 0x28A6 + 0xE0 * 4) == 0x135E
        assert jump(code, 0x28A6 + 8 * 4) == 0x0B10
        assert jump(code, 0x1382 + 0x0E * 4) == 0x1630
        assert jump(code, 8) == 0x4A
        drivers.append({'driver': driver, 'E0_target': '135E', '08_target': '0B10',
                        'C00E_target': '1630', 'initialization_target': '004A',
                        'zero_mode_renderer': '4360' if driver == 5 else '4146',
                        'renderer_windows': {f'{site:04X}': value for site, value in variant.items()}})
        inputs.append(path)
    source = ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin'
    slot_pins = ROOT / 'fixtures/experiments/card-slot3-recovery/results.json'
    assert sha(source) == json.loads(slot_pins.read_text())['inputs_sha256'][str(source)]
    expected = '226dedf82269000222513029000402403fff3b40f778206df7a64ea80004'
    assert source.read_bytes()[0x42D4:0x42D4 + len(expected) // 2].hex() == expected
    inputs += [source, pins_path, slot_pins, Path(__file__)]
    result = {'scope': 'static original-byte checks; renderer initialization not executed',
        'drivers': drivers, 'driver_windows': {f'{site:04X}': value for site, value in checks.items()},
        'CODE1_42D4_window': expected,
        'renderer_prerequisites': {'A5_minus_085E': 'display destination from driver initialization',
            'A5_minus_0888': 'row stride from original PixMap setup',
            'A5_minus_1062': 'CODE5 lores row offsets; CODE6 computes row*16*stride directly',
            'A5_minus_0974': 'resolved display mode, not an arbitrary zero default'},
        'inputs_sha256': {str(path): sha(path) for path in inputs}}
    (HERE / 'init-contract.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS original first-switch dispatch and renderer initialization windows')


if __name__ == '__main__':
    main()
