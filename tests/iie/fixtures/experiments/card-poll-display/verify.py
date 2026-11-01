#!/usr/bin/env python3
"""Verify polling/display records and source/capture hashes."""
import hashlib
import json
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    records = list(folder.glob('*.json'))
    assert len(records) == 4
    found = set()
    for path in records:
        record = json.loads(path.read_text())
        driver, fault = record['driver'], record['poll_control']
        found.add((driver, fault))
        expected = {'status': 'live prompt pixel mismatch',
                    'pause': 'runtime hold blocked pending response'}.get(fault)
        assert record['rejected'] == expected
        assert record['key_delivery'] is None and record['prelude_pds_requests'] == 6
        assert record['protocol_requests'] == len(record['transactions'])
        if not fault:
            assert record['total_pds_requests'] == 6659
            assert len(record['transactions']) == 6644
        for name, digest in record['inputs_sha256'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
        run = Path(record['run_directory'])
        for name, digest in record['capture_sha256'].items():
            assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest, name
    assert found == {(5, None), (6, None), (5, 'status'), (5, 'pause')}
    for path in folder.glob('*.py'):
        compile(path.read_text(), str(path), 'exec')
    for path in folder.iterdir():
        if path.is_file():
            assert all(line.isascii() and line == line.rstrip() for line in path.read_text().splitlines()), path
    print('PASS polling/display cases, controls, source/capture hashes and source hygiene')


if __name__ == '__main__':
    main()
