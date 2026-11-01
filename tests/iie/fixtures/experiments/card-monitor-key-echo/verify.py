#!/usr/bin/env python3
"""Verify the input-buffer and echo evidence matrix."""
import hashlib
import json
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    paths = list(folder.glob('*.json'))
    assert len(paths) == 12
    found = set()
    for path in paths:
        result = json.loads(path.read_text())
        fault = result['echo_control']
        found.add((result['driver'], result['profile'], result['key'], fault))
        assert not any(result[field] for field in ('control', 'key_control', 'prompt_control', 'routing_control', 'switch_control'))
        assert result['finish_init'] and len(result['transactions']) == 314 and len(result['register_records']) == 67
        assert result['prelude_pds_requests'] == 16 and result['total_pds_requests'] == 331
        assert result['key_delivery'] == {'write': True, 'width': 8, 'offset': 24, 'value': int(result['key'], 16),
                                          'keyboard_write_pulses': 1, 'pds_requests_after_delivery': 281}
        output = result['rtl_result']
        assert sum(line.startswith('KEY_RESULT') for line in output) == 1
        assert sum(line.startswith('BUFFER_WRITE address=0200') for line in output) == 1
        if fault:
            marker = 'input buffer store missing' if fault == 'buffer' else 'key echo store missing'
            assert marker in result['rejected'] and any(marker in line for line in output)
            assert not any(line.startswith(('PASS key-echo', 'ECHO_RESULT')) for line in output)
        else:
            assert result['rejected'] is None
            counts = {'41': (32687, 2503, 34737), '15': (32699, 2503, 34748), '7f': (33072, 2531, 35143)}
            cpu, writes, backend = counts[result['key']]
            marker = f'PASS key-echo fast=1 next_PC=c267 service=6 CPU={cpu} writes={writes} backend={backend}'
            assert any(line.startswith(marker) for line in output)
            assert sum(line.startswith('ECHO_RESULT') for line in output) == 1
        for name, digest in result['inputs_sha256'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
        run = Path(result['run_directory'])
        for name, digest in result['capture_sha256'].items():
            assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest, name
    expected = {(driver, profile, key, fault) for driver in (5, 6) for profile, key, fault in (
        ('slot6', '41', None), ('override', '41', None), ('slot6', '15', None), ('slot6', '7f', None),
        ('slot6', '41', 'buffer'), ('slot6', '41', 'echo'))}
    assert found == expected
    for path in folder.glob('*.py'):
        compile(path.read_text(), str(path), 'exec')
    for path in folder.iterdir():
        if path.is_file():
            assert all(line.isascii() and line == line.rstrip() for line in path.read_text().splitlines()), path
    print('PASS twelve echo cases, source/capture hashes, syntax, ASCII and whitespace')


if __name__ == '__main__':
    main()
