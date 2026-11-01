#!/usr/bin/env python3
"""Check the original key prefix, input-buffer store and echo branches."""
import importlib.util
import os
from prepare import KEY

spec = importlib.util.spec_from_file_location('echo_key_checks', KEY / 'checks.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def check_host(driver, run, snapshots, records, output, render, control, transactions):
    parent.check_host(driver, run, snapshots, records, output, render, control, transactions)
    key = int(os.environ['IIE_KEY'], 16)
    fault = os.environ['IIE_ECHO_CONTROL']
    lines = (run / 'echo-instructions.txt').read_text().splitlines()
    pcs = [int(line[:4], 16) for line in lines]
    value = 0xa0 if key == 0x15 else 0x88 if key == 0x7f else 0xc1
    assert pcs[0] == 0xfd7a
    for address in (0xfd7a, 0xfd84, 0xfd47, 0xfded, 0xfbf0, 0xfbf2, 0xfbf4):
        count = 3 if key == 0x7f and address == 0xfded else 1
        assert pcs.count(address) == count, (hex(address), count)
    assert pcs.count(0xfd7c) == int(key == 0x15)
    assert pcs.count(0xfd71) == 2 * int(key == 0x7f)
    assert pcs.count(0xfd67) == int(key == 0x7f)
    assert pcs.count(0xfd5f) == int(key != 0x7f)
    assert [line for line in output if line.startswith('BUFFER_WRITE')] == [f'BUFFER_WRITE address=0200 data={value:02x}']
    writes = [line for line in output if line.startswith('PROMPT_WRITE')][-3:]
    expected = ([('0580', 'dd'), ('07f8', '31'), ('0581', '60')] if key == 0x7f else
                [('0501', f'{value:02x}'), ('07f8', '31'), ('0502', '60')])
    assert writes == [f'PROMPT_WRITE address={address} data={data}' for address, data in expected]
    assert len(records) == 67 and len(transactions) == 314
    if fault:
        marker = 'input buffer store missing' if fault == 'buffer' else 'key echo store missing'
        assert any(marker in line for line in output)
        assert not any(line.startswith('PASS key-echo') for line in output)
        assert not any(line.startswith('ECHO_RESULT') for line in output)
        return
    assert lines[-1].startswith('c25f 10 ')
    ch, cv, x = (1, 3, 0) if key == 0x7f else (2, 2, 1)
    assert [line for line in output if line.startswith('ECHO_RESULT')] == [
        f'ECHO_RESULT raw={key:02x} buffer={value:02x} CH={ch:02x} CV={cv:02x} X={x:02x} stack=ef seed=0105']
    assert any(line.startswith('PASS key-echo fast=1 next_PC=c267 service=6 ') for line in output)
