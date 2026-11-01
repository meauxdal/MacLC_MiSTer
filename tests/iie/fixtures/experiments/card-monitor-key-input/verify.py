#!/usr/bin/env python3
"""Verify the complete original key-input evidence matrix."""
import hashlib
import json
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    records = list(folder.glob('*.json'))
    assert len(records) == 12
    found = set()
    for path in records:
        result = json.loads(path.read_text())
        fault = result['key_control']
        found.add((result['driver'], result['profile'], result['key'], fault))
        assert not result['control'] and result['prompt_control'] is None and not result['routing_control']
        assert not result['switch_control'] and result['finish_init']
        assert len(result['transactions']) == (264 if fault else 314)
        assert len(result['register_records']) == (56 if fault else 67)
        delivery = result['key_delivery']
        assert delivery == {'write': True, 'width': 8, 'offset': 24, 'value': int(result['key'], 16),
                            'keyboard_write_pulses': 1, 'pds_requests_after_delivery': 281}
        assert result['prelude_pds_requests'] == 16
        assert result['total_pds_requests'] == len(result['transactions']) + 17
        if fault:
            marker = 'key strobe creation missing' if fault == 'strobe' else 'key clear completion missing'
            assert marker in result['rejected']
            assert not any(line.startswith('PASS key-input') for line in result['rtl_result'])
        else:
            assert result['rejected'] is None
            assert any('PASS key-input fast=1 next_PC=fd7a service=6 CPU=32321 writes=2478 backend=34353' in line
                       for line in result['rtl_result'])
        for name, digest in result['inputs_sha256'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
        run = Path(result['run_directory'])
        for name, digest in result['capture_sha256'].items():
            assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest, name
    expected = {(driver, profile, key, fault) for driver in (5, 6) for profile, key, fault in (
        ('slot6', '41', None), ('override', '41', None), ('slot6', '15', None), ('slot6', '7f', None),
        ('slot6', '41', 'strobe'), ('slot6', '41', 'clear'))}
    assert found == expected
    for path in folder.glob('*.py'):
        compile(path.read_text(), str(path), 'exec')
    for path in folder.iterdir():
        if path.is_file():
            assert all(line.isascii() and line == line.rstrip() for line in path.read_text().splitlines()), str(path)
    print('PASS twelve key-input cases, all source/capture hashes, syntax, ASCII and whitespace')


if __name__ == '__main__':
    main()
