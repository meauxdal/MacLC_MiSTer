#!/usr/bin/env python3
"""Verify continuous initializer evidence and source/capture closure."""
import hashlib
import json
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    records = list(folder.glob('results-*.json'))
    assert len(records) == 2
    assert {json.loads(path.read_text())['driver'] for path in records} == {5, 6}
    for path in records:
        record = json.loads(path.read_text())
        assert record['rejected'] is None and record['total_pds_requests'] == 6659
        for name, digest in record['inputs_sha256'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
        run = Path(record['run_directory'])
        for name, digest in record['capture_sha256'].items():
            assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest, name
    for path in folder.glob('*.py'):
        compile(path.read_text(), str(path), 'exec')
    for path in folder.iterdir():
        if path.is_file():
            assert all(line.isascii() and line == line.rstrip() for line in path.read_text().splitlines()), path
    print('PASS both continuous initializers, source/capture hashes and source hygiene')


if __name__ == '__main__':
    main()
