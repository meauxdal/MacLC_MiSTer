#!/usr/bin/env python3
"""Retain host-service checks while the original CPU prints its prompt."""
import importlib.util
import os
import re
from prepare import POST, once


def check_host(*args):
    driver, run, snapshots, records, output, render, control, transactions = args
    fault = os.environ['IIE_PROMPT_CONTROL']
    source = (POST / 'checks.py').read_text()
    source = once(source, "assert scan[-1].startswith('f1d0 84 ')",
                  "assert any('prompt store missing before input' in line for line in output)" if fault == 'store' else
                  "assert scan[-1].startswith('c28f 10 ')")
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('prompt_checks', loader=None))
    exec(compile(source, str(POST / 'checks.py'), 'exec'), module.__dict__)
    module.check_host(*args)
    scan = (run / 'instructions.txt').read_text().splitlines()
    pcs = [int(line[:4], 16) for line in scan]
    for address in (0xf1d2, 0xd43c, 0xd43f, 0xd441, 0xd52e, 0xfd6a, 0xfd75, 0xfd35,
                    0xfd28, 0xfd0c, 0xfd1b):
        assert pcs.count(address) == 1, (hex(address), pcs.count(address))
    writes = [tuple(int(item, 16) for item in pair) for pair in re.findall(
        r'^PROMPT_WRITE address=([0-9a-f]+) data=([0-9a-f]+)$', '\n'.join(output), re.M)]
    assert writes == [(0x500, 0xdd), (0x7f8, 0x62), (0x501, 0x60)] + ([] if fault == 'store' else [(0x501, 0xff)])
    if fault == 'store':
        assert scan[-1].startswith('c25f 10 ') and pcs.count(0xc267) == pcs.count(0xc28c) == 0
    else:
        assert pcs.count(0xc267) == 1 and pcs.count(0xc27b) == 1
        assert pcs.count(0xc27d) == pcs.count(0xc27f) == pcs.count(0xc28c) == pcs.count(0xc28f) == 260
        assert pcs.count(0xc281) == pcs.count(0xc283) == pcs.count(0xc285) == pcs.count(0xc287) == 1
        assert not any(address in pcs for address in (0xc291, 0xc29b, 0xc83b, 0xfd78))
        assert any('INPUT_ENTRY seed=0000 cursor=01 row=02 base=0500 vectors=fdf0/fd1b' in line for line in output)
    if fault:
        assert not any(line.startswith('PASS prompt') for line in output)
        if fault == 'seed':
            assert any('idle seed carry missing expected=0104 actual=0004' in line for line in output)
    else:
        assert any('IDLE reads=260 seed=0104 cursor=0501 prompt=dd cell=ff CH=01 CV=02' in line for line in output)
