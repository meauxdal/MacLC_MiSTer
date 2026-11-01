#!/usr/bin/env python3
"""Check native firmware uploads and the uninterrupted runtime endpoint."""
import importlib.util
from prepare import CONTINUOUS


def check_host(*args):
    spec = importlib.util.spec_from_file_location('upload_runtime_checks', CONTINUOUS / 'checks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_host(*args)
    driver, run, snapshots, records, output, render, control, transactions = args
    assert (run / 'upload-code.bin').read_bytes() == (render.CODE / 'CODE_1.bin').read_bytes()
    assert any(line.startswith('UPLOAD_COMPLETE') for line in output)
    assert sum(write and width == 8 and offset == 16 for write, width, offset, value in transactions) >= 38438
