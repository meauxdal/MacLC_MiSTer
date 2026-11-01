#!/usr/bin/env python3
"""Verify the complete prompt fixture's evidence matrix."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    records = list(HERE.glob('*.json'))
    assert len(records) == 8
    found = set()
    for path in records:
        result = json.loads(path.read_text())
        fault = result['prompt_control']
        found.add((result['driver'], result['profile'], fault))
        assert len(result['transactions']) == 264 and len(result['register_records']) == 56
        assert not result['control'] and not result['routing_control'] and not result['switch_control']
        assert result['finish_init']
        if fault:
            marker = 'prompt store missing before input' if fault == 'store' else 'idle seed carry missing expected=0104 actual=0004'
            assert marker in result['rejected']
            assert not any(line.startswith('PASS prompt') for line in result['rtl_result'])
        else:
            assert result['rejected'] is None
            assert any('PASS prompt fast=1 next_PC=c27d' in line for line in result['rtl_result'])
        for name, digest in result['inputs_sha256'].items():
            assert sha(Path(name)) == digest, (path.name, name)
        run = Path(result['run_directory'])
        for name, digest in result['capture_sha256'].items():
            assert sha(run / name) == digest, (path.name, name)
    expected = {(driver, profile, fault) for driver in (5, 6)
                for profile, fault in (('slot6', None), ('override', None), ('slot6', 'store'), ('slot6', 'seed'))}
    assert found == expected
    for path in HERE.glob('*.py'):
        compile(path.read_text(), str(path), 'exec')
    for path in HERE.iterdir():
        if path.is_file():
            assert all(line.isascii() and line == line.rstrip() for line in path.read_text().splitlines()), str(path)
    print('PASS eight prompt cases, source/capture hashes, syntax, ASCII and whitespace')


if __name__ == '__main__':
    main()
