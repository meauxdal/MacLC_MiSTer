#!/usr/bin/env python3
"""Check original boot-service selection and the next monitor service."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-boot-contract'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(data, offset, expected):
    assert data[offset:offset + len(expected) // 2].hex() == expected, hex(offset)


def jump(data, offset):
    check(data, offset, '4efa')
    return offset + 2 + int.from_bytes(data[offset + 2:offset + 4], 'big', signed=True)


def saved_a(flag, settings):
    value = 6
    if flag == 0:
        value = settings & 15
        if value == 1:
            value = 8
    return value | 0xc0


def main():
    dispatch_path = ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json'
    monitor_pins_path = ROOT / 'fixtures/experiments/card-monitor-entry/results-1.json'
    dispatch_pins = json.loads(dispatch_path.read_text())['inputs_sha256']
    monitor_pins = json.loads(monitor_pins_path.read_text())['inputs_sha256']
    monitor_path = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    assert sha(monitor_path) == monitor_pins[str(monitor_path)]
    monitor = monitor_path.read_bytes()
    monitor_window = '020286008501a005c601a5010203f0d78df807'
    check(monitor, 0x3ab4, monitor_window)
    windows = {
        0x1cbc: '4efa00a8',
        0x1cc0: '4efa00c8',
        0x1d66: '103c0006122da7ec6610302df7940200000f0c00000166027008000000c01b40f76c4e75',
        0x1d8a: '122da7ec6710122df76c0c0100c4661e422da7ec602c302df7940200000f0c0000016612122df76c0c4100c0675408ad0001f76f4e75',
        0x1dc0: '5500000000c0b02df76c66ec',
        0x1dcc: '598f2f3c535452203f3c5101a9a0201f672e',
        0x1e0c: '08ed0001f76f4e75',
        0x36c: '32350320eeba0c415000660c43f50520ee3a2b49f79a60100c415100660a43f50520ee3a2b49f79e',
        0x3b8: '20758161f79a20503b50f794',
    }
    inputs = [HERE / 'analyze.py', dispatch_path, monitor_pins_path, monitor_path]
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        assert sha(path) == dispatch_pins[str(path.relative_to(ROOT))]
        code = path.read_bytes()
        for offset, expected in windows.items():
            check(code, offset, expected)
        assert jump(code, 0x1cbc) == 0x1d66
        assert jump(code, 0x1cc0) == 0x1d8a
        inputs.append(path)
    cases = []
    for flag in (0, 1, 255):
        for high in (0, 0xa5f0):
            for nibble in range(16):
                settings = high | nibble
                value = saved_a(flag, settings)
                expected = 0xc6 if flag else 0xc8 if nibble == 1 else 0xc0 | nibble
                assert value == expected
                cases.append({'flag': flag, 'settings_word': settings, 'saved_a': value,
                              'next_service3_a': (value - 1) & 255})
    controls = {'zero_state_forced_default_6': 0xc6,
                'nonzero_flag_incorrectly_uses_settings_1': 0xc8}
    assert controls['zero_state_forced_default_6'] != saved_a(0, 0)
    assert controls['nonzero_flag_incorrectly_uses_settings_1'] != saved_a(1, 1)
    WORK.mkdir(parents=True, exist_ok=True)
    matrix = WORK / 'selection-cases.json'
    matrix.write_text(json.dumps(cases, indent=2) + '\n', encoding='ascii')
    result = {'scope': 'static original-byte contract and branch model; no guest execution',
        'entry': 0x1d66, 'service2_table': 0x1cbc,
        'dependencies': {'flag_a5': -0x5814, 'settings_word_a5': -0x86c, 'saved_a_a5': -0x894},
        'writes': ['saved A only'],
        'zero_state': {'saved_a': 0xc0, 'next_service3_a': 0xbf, 'next_monitor_pc': 0xfac0},
        'code_windows': {f'{offset:04X}': value for offset, value in windows.items()},
        'monitor_windows': {'FAB4': monitor_window}, 'branch_cases': len(cases),
        'controls': controls, 'inputs_sha256': {str(p): sha(p) for p in inputs},
        'captures_sha256': {str(matrix): sha(matrix)}}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS CODE5/6 BS2 selection bytes; 96 static cases; BS3 next boundary')


if __name__ == '__main__':
    main()
