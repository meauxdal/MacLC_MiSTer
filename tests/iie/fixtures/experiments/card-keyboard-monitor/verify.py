#!/usr/bin/env python3
"""Verify the eight keyboard records and lint the generated card closure."""
import importlib.util
import json
import shlex
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('keyboard_monitor_prepare', HERE / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def main():
    records = [HERE / f'{kind}-{driver}-48{suffix}.json'
               for driver in (5, 6) for kind in ('results', 'control')
               for suffix in ('', '-deferred')]
    cache = {}

    def digest(path):
        if path not in cache:
            cache[path] = prepare.sha(path)
        return cache[path]

    for path in records:
        record = json.loads(path.read_text())
        for name, expected in record['inputs_sha256'].items():
            assert digest(Path(name)) == expected, name
        run = record['runs'][0]
        folder = Path(run['run_directory'])
        for name, expected in run['hashes'].items():
            assert digest(folder / name) == expected, str(folder / name)
        count = (111 if run['deferred_drain'] else 106) if run['control'] else (112 if run['deferred_drain'] else 111)
        assert len(run['transactions']) == count
        assert run['event_writes_forwarded'] == (1 if run['control'] else 2)
        assert run['acks_forwarded'] == 2
        assert run['rejected'] == ('keyboard strobe clear missing' if run['control'] else None)
    for path in HERE.iterdir():
        if path.suffix in ('.py', '.md', '.json'):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                assert line.isascii() and line.rstrip() == line, (str(path), number)
            if path.suffix == '.py':
                compile(path.read_text(), str(path), 'exec')
    sources, _, _ = prepare.prepare()
    command = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME',
        '-Wno-PINCONNECTEMPTY', '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps',
        '--top-module', 'maclc_iie_binding', *map(linux, sources[1:])]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    print('PASS eight records, input/capture hashes, syntax/ASCII/whitespace and card closure lint')


if __name__ == '__main__':
    main()
