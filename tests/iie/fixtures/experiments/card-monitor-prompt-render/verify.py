#!/usr/bin/env python3
"""Verify original prompt-render evidence and its source/capture closure."""
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
        fault = result['render_control']
        found.add((result['driver'], result['profile'], result['key'], fault))
        assert not any(result[name] for name in ('control', 'routing_control', 'switch_control', 'prompt_control', 'key_control', 'echo_control'))
        assert result['finish_init'] and len(result['transactions']) == 1354 and len(result['register_records']) == 68
        assert result['refreshed_bytes'] == 1024 and result['rendered_cells'] == 960 and result['pixels_checked'] == 307200
        assert result['protocol_requests'] == 1355 and result['total_pds_requests'] == 1371 and result['prelude_pds_requests'] == 16
        assert result['key_delivery'] == {'write': True, 'width': 8, 'offset': 24, 'value': int(result['key'], 16),
                                          'keyboard_write_pulses': 1, 'pds_requests_after_delivery': 281}
        assert result['rejected'] == ('prompt pixel or framebuffer guard mismatch' if fault else None)
        output = result['rtl_result']
        for marker in ('KEY_RESULT', 'ECHO_RESULT', 'RENDER_READY', 'RENDER_ACK empty=1', 'RENDER_ACCOUNT'):
            assert sum(line.startswith(marker) for line in output) == 1, marker
        cpu, writes, backend = {'41': (32687, 2503, 35761), '15': (32699, 2503, 35772),
                               '7f': (33072, 2531, 36167)}[result['key']]
        marker = f'PASS prompt-render fast=1 next_PC=c267 service=6 CPU={cpu} writes={writes} backend={backend}'
        assert any(line.startswith(marker) for line in output)
        assert 'RENDER_ACCOUNT guest=1354 delivery=1 prelude=16 protocol=1355 total=1371' in output
        for name, digest in result['inputs_sha256'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
        run = Path(result['run_directory'])
        for name, digest in result['capture_sha256'].items():
            assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest, name
    expected = {(driver, profile, key, fault) for driver in (5, 6) for profile, key, fault in (
        ('slot6', '41', None), ('override', '41', None), ('slot6', '15', None), ('slot6', '7f', None),
        ('slot6', '41', 'glyph'), ('slot6', '41', 'destination'))}
    assert found == expected
    for path in folder.glob('*.py'):
        compile(path.read_text(), str(path), 'exec')
    for path in folder.iterdir():
        if path.is_file():
            assert all(line.isascii() and line == line.rstrip() for line in path.read_text().splitlines()), path
    print('PASS twelve prompt-render cases, source/capture hashes, syntax, ASCII and whitespace')


if __name__ == '__main__':
    main()
