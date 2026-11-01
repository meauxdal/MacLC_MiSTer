#!/usr/bin/env python3
"""Check original service-3 branches, resource bounds and monitor reads."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-boot-service3-contract'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    contract_path = HERE.parent / 'card-boot-contract/results.json'
    pins = json.loads(contract_path.read_text())['inputs_sha256']
    windows = {
        0x1d8a: '122da7ec6710122df76c0c0100c4661e422da7ec602c302df7940200000f0c0000016612122df76c0c4100c0675408ad0001f76f4e75',
        0x1dc0: '5500000000c0b02df76c66ec598f2f3c535452203f3c5101a9a0201f672e',
        0x1dde: '2f002040a02922507400141924490c4200796502747822020019008051c9fffa7600363c06004ebae778205fa02a08ed0001f76f4e75',
    }
    inputs = [HERE / 'analyze.py', contract_path]
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        assert sha(path) == pins[str(path)]
        code = path.read_bytes()
        assert code[0x1cc0:0x1cc4].hex() == '4efa00c8'
        for offset, data in windows.items():
            assert code[offset:offset + len(data) // 2].hex() == data
        inputs.append(path)
    monitor = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    assert sha(monitor) == pins[str(monitor)]
    assert monitor.read_bytes()[0x3ac2:0x3ad5].hex() == 'f0d78df807b100d901fbd0ec888810f56c0000'
    inputs.append(monitor)
    resource_pins = HERE.parent / 'card-reload-callback/results-5-4a.json'
    original_pins = json.loads(resource_pins.read_text())['inputs_sha256']
    metadata = ROOT / 'local/experiments/firmware-memory/resources.json'
    fork = ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc'
    for path in (metadata, fork):
        assert sha(path) == original_pins[str(path)]
    item = next(entry for entry in json.loads(metadata.read_text())['resources']
                if entry['type'] == 'STR ' and entry['id'] == 0x5101)
    resource = fork.read_bytes()[item['fork_offset']:item['fork_offset'] + item['size']]
    assert hashlib.sha256(resource).hexdigest() == item['sha256']
    assert len(resource) == 77 and resource[0] == 76
    inputs += [resource_pins, metadata, fork]
    cases = [
        {'profile': 'slot6', 'initial_a': 0xc5, 'first_p_action': 'clear bit 1',
         'first_signature_read': 0xc505, 'matching_a': 0xc4, 'conditional_call_number': 2,
         'matching_path': 'STR 5101'},
        {'profile': 'slot8', 'initial_a': 0xc7, 'first_p_action': 'clear bit 1',
         'first_signature_read': 0xc705, 'matching_a': 0xc0, 'conditional_call_number': 8,
         'matching_path': 'set bit 1 without resource'},
        {'profile': 'override', 'initial_a': 0xc5, 'first_p_action': 'clear bit 1',
         'first_signature_read': 0xc505, 'matching_a': 0xc4, 'conditional_call_number': 2,
         'matching_path': 'clear flag then STR 5101'},
    ]
    assert (0x25 & ~2) == 0x25
    assert (0x25 | 2) != 0x25
    WORK.mkdir(parents=True, exist_ok=True)
    extracted = WORK / 'STR_5101.bin'
    extracted.write_bytes(resource)
    result = {'scope': 'static original-byte service3 contract; no guest execution',
        'windows': {f'{offset:04X}': data for offset, data in windows.items()},
        'initial_profiles': cases,
        'resource': {'type': 'STR ', 'id': 0x5101, 'fork_offset': item['fork_offset'],
            'size': len(resource), 'prefix_length': resource[0], 'sha256': item['sha256'],
            'transform_bytes_after_prefix': resource[0] + 1, 'bytes_past_resource': 1,
            'logical_display_address': 0x600},
        'controls': {'skipped_clear_when_p_25': 'inert', 'wrong_set_when_p_25': 'differs'},
        'inputs_sha256': {str(path): sha(path) for path in inputs},
        'captures_sha256': {str(extracted): sha(extracted)}}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS original CODE5/6 service3 bytes, STR5101 bounds and monitor-read contract')


if __name__ == '__main__':
    main()
