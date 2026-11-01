#!/usr/bin/env python3
"""Retain matching-service checks and verify the original cold-start trace."""
import importlib.util
import os
from prepare import MATCH, once


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    source = (MATCH / 'checks.py').read_text()
    routing = os.environ['IIE_WRONG_E000'] == '1'
    finish = os.environ['IIE_FINISH_INIT'] == '1'
    switch = os.environ['IIE_WRONG_SWITCH'] == '1'
    source = once(source, "assert scan[-1].startswith('fac2 f0 A=c4 ')",
                  "assert scan[-1].startswith('e000 00 ')" if routing else
                  "assert scan[-1].startswith('f187 91 ')" if switch else
                  "assert scan[-1].startswith('f1d0 84 ')" if finish else
                  "assert scan[-1].startswith('f181 e6 ')")
    source = once(source, 'SCAN next_A=c4 next_PC=fa9b external_reads=1',
                  'next_PC=f183 external_reads=1')
    if routing:
        source = once(source, "        assert any('next_PC=f183 external_reads=1' in line for line in output)",
            "        assert any('cold E000 routing mismatch physical=26000' in line for line in output)")
    elif switch:
        source = once(source, "        assert any('next_PC=f183 external_reads=1' in line for line in output)",
                      "        assert not any(line.startswith('PASS post-match') for line in output)")
    elif finish:
        source = once(source, 'next_PC=f183 external_reads=1', 'next_PC=f1d2 external_reads=1')
    if finish and not routing and not control:
        total = 262 if switch else 264
        source = once(source, 'len(records) == (51 if control else 55)', f'len(records) == {55 if switch else 56}')
        source = once(source, 'assert position == len(records)', f'assert position == len(records) - {int(not switch)}')
        source = source.replace('transactions=260', f'transactions={total}')
        if switch:
            source = once(source, 'pc=20281c sp=3f0000', 'pc=2028c6 sp=3f0000')
        source = once(source, 'assert len(transactions) == 260', f'assert len(transactions) == {total}')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('matching_checks', loader=None))
    exec(compile(source, str(MATCH / 'checks.py'), 'exec'), module.__dict__)
    module.check_host(driver, run, snapshots, records, output, render, control, transactions)
    if control:
        return
    scan = (run / 'instructions.txt').read_text().splitlines()
    pcs = [int(line[:4], 16) for line in scan]
    assert pcs.count(0xfa9b) == pcs.count(0xfa9d) == pcs.count(0xfaa0) == 1
    if routing:
        assert pcs.count(0xe000) == 1 and pcs.count(0xf128) == 0
        assert not any(line.startswith('PASS post-match') for line in output)
        return
    assert pcs.count(0xe000) == pcs.count(0xf128) == 1
    assert pcs.count(0xf183) == 183 + int(finish) and pcs.count(0xf187) == 183 + int(finish)
    assert pcs.count(0xf18f) == 183 and pcs.count(0xf195) == int(finish and not switch)
    if switch:
        assert transactions[-2:] == [[False, 8, 1, 8], [False, 8, 1, 8]]
        assert (run / 'cold-route-world.bin').read_bytes() == (run / 'match-world.bin').read_bytes()
        trace = (run / 'trace.txt').read_text()
        assert trace.rstrip().endswith('002028C6: jmp     ($200b10,PC)')
        assert not (run / 'cold-switch-world.bin').exists()
    elif finish:
        assert transactions[-4:] == [[False, 8, 1, 0xe0], [False, 8, 1, 0xe0], [False, 16, 4, 0xc000], [True, 8, 12, 0]]
        assert records[-1][2:4] == [12, 0] and records[-1][4:] == records[-2][4:]
        assert (run / 'cold-switch-world.bin').read_bytes() == (run / 'match-world.bin').read_bytes()
        assert (run / 'cold-switch-code.bin').read_bytes() == (run / 'match-code.bin').read_bytes()
        assert pcs.count(0xf1bf) == pcs.count(0xf1ce) == 1
        assert any('SIZING entries=1 probes=184 writes=366 next_page=c0 next_PC=f1d2' in line for line in output)
    else:
        assert any('SIZING entries=1 probes=183 writes=366 next_page=c0 next_PC=f183' in line for line in output)
