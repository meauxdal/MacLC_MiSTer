#!/usr/bin/env python3
"""Pinned real loader with isolated mount admission and retained metadata."""
import hashlib
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/maclc-loader-quiesce'
MACLC = Path('C:/Workspace/Git/MacLC_MiSTer')
PIN = '511ab0548c7f4f2d712bdc737b6442b006264ecaca75f01a5383ce3fa0424988'


def prepare():
    raw = (MACLC / 'rtl/floppy_sd.v').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PIN
    source = raw.decode('utf-8').replace('\r\n', '\n')
    source = source[source.index('module floppy_loader'):]
    source = source[:source.index('endmodule') + len('endmodule')]
    # Keep executable source unchanged; remove inherited non-ASCII prose.
    source = '\n'.join(line.split('//')[0].rstrip() for line in source.splitlines())
    source = source.replace('module floppy_loader', 'module pinned_floppy_loader', 1)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'loader.sv').write_text(source + '\n', encoding='ascii')
    spec = importlib.util.spec_from_file_location('download_prepare', HERE.parent / 'maclc-download-quiesce/prepare.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.prepare()
    return helper.WORK


if __name__ == '__main__':
    prepare()
