#!/usr/bin/env python3
"""Exercise memory switches with the active card CPU and host capture interface."""
import json
from pathlib import Path

from prepare_runtime import ROOT, WORK, runtime_sources, sha
from check_runtime import linux, run, run_process


def main():
    sources = runtime_sources()
    program = bytearray()
    expected = []

    def emit(*values):
        program.extend(values)

    def access(address, write=False):
        emit(0x8d if write else 0xad, address & 255, address >> 8)

    def load(value):
        emit(0xa9, value)

    def report(address, value):
        access(address)
        access(0xc07d, True)
        expected.append(value)

    def statuses(bank2, read, ramrd, ramwrt, altzp):
        for address, bit in zip((0xc011, 0xc012, 0xc013, 0xc014, 0xc016),
                                (bank2, read, ramrd, ramwrt, altzp)):
            report(address, bit << 7)

    statuses(1, 0, 0, 0, 0)
    for address in (0xc003, 0xc005, 0xc009):
        access(address, True)
    statuses(1, 0, 1, 1, 1)
    for address in (0xc002, 0xc004, 0xc008):
        access(address, True)
    statuses(1, 0, 0, 0, 0)

    # Write access changes read/bank selection, but cannot arm LC writes.
    access(0xc082)
    access(0xc08b, True)
    statuses(0, 1, 0, 0, 0)
    access(0xc08b)
    load(0x99)
    access(0xd000, True)
    report(0xd000, 0x31)
    # A write between odd reads must break the prewrite sequence.
    access(0xc08b, True)
    access(0xc08b)
    load(0x98)
    access(0xd000, True)
    report(0xd000, 0x31)
    access(0xc08b)
    load(0x51)
    access(0xd000, True)
    report(0xd000, 0x51)

    access(0xc083)
    access(0xc083)
    statuses(1, 1, 0, 0, 0)
    report(0xd000, 0x32)
    load(0x52)
    access(0xd000, True)
    report(0xd000, 0x52)
    access(0xc08b)
    report(0xd000, 0x51)

    access(0xc009, True)
    report(0xd000, 0x41)
    load(0x61)
    access(0xd000, True)
    report(0xd000, 0x61)
    access(0xc083)
    report(0xd000, 0x42)
    access(0xc008, True)
    report(0xd000, 0x52)

    # ROM reads and RAM writes coexist; E000 must not hit diagnostic firmware.
    access(0xc081)
    access(0xc081)
    report(0xc012, 0)
    load(0x73)
    access(0xe000, True)
    access(0xc083)
    report(0xe000, 0x73)
    access(0xc082)
    load(0x97)
    access(0xe000, True)
    access(0xc080)
    report(0xe000, 0x73)
    # Language RAM owns its vectors too; ROM vector storage stays separate.
    access(0xc083)
    access(0xc083)
    for address, value in ((0xfffa, 0x81), (0xfffc, 0x82), (0xfffe, 0x83)):
        load(value)
        access(address, True)
        report(address, value)
    access(0xc009, True)
    for address, value in ((0xfffa, 0x91), (0xfffc, 0x92), (0xfffe, 0x93)):
        report(address, 0)
        load(value)
        access(address, True)
        report(address, value)
    access(0xc008, True)
    report(0xfffc, 0x82)
    access(0xc082)
    report(0xfffc, 0x62)
    emit(0x4c, 0x00, 0x20)

    memory = bytearray(262144)
    for base in (0x2000, 0x12000):
        memory[base:base + len(program)] = program
    memory[0x23a62:0x23a65] = bytes.fromhex('4c0020')
    memory[0x27ffc:0x27ffe] = bytes.fromhex('62fa')
    for address, value in ((0xc000, 0x31), (0xd000, 0x32),
                           (0x1c000, 0x41), (0x1d000, 0x42)):
        memory[address] = value
    image = WORK / 'banking-runtime.hex'
    image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "little"):04x}\n'
                             for i in range(0, len(memory), 2)), encoding='ascii')
    results = WORK / 'banking-expected.hex'
    results.write_text(''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
    bench = ROOT / 'tools/tb_banking_runtime.sv'
    binary = WORK / 'banking-runtime.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_banking_runtime', '-o', linux(binary),
         linux(bench), *map(linux, sources)])
    command = ['vvp', linux(binary), '+image=' + linux(image),
               '+expected=' + linux(results), f'+count={len(expected)}']
    output = run(command)
    delayed = run([*command, '+latency=73'])
    controls = {}
    for name, failure in (('status-control', 'bank result 0 '),
                          ('rom-control', 'bank result 36 ')):
        result = run_process([*command, '+' + name])
        assert result.returncode != 0 and failure in result.stdout, result.stdout + result.stderr
        controls[name] = result.stdout
        print('PASS rejected ' + name)
    record = {'result': output, 'delayed_memory': delayed, 'reports': len(expected), 'controls': controls,
              'scope': 'Synthetic CPU program, real card capture/ACK and memory arbitration; no original Startup or hardware',
              'sha256': {str(p): sha(p) for p in [*sources, bench, Path(__file__), image, results]}}
    (WORK / 'banking-runtime.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
