#!/usr/bin/env python3
"""Check live CPU display captures and the original drivers' dispatch entries."""
import json
from pathlib import Path

from prepare_runtime import ROOT, WORK, runtime_sources, sha
from check_runtime import linux, run, run_process


def main():
    sources = runtime_sources()
    program, cases = bytearray(), []
    addresses = (0x400, 0x7ff, 0x800, 0xbff, 0x2000, 0x23ff,
                 0x2400, 0x3fff, 0x4000, 0x43ff, 0x4400, 0x5fff)
    masks = (0, 0x20, 0x10, 0x30, 0x28, 0x18, 0x38,
             0x80, 0x40, 0xc0, 0x84, 0x44, 0xc4, 0xac, 0x5c)
    used_status = set()
    for mask in masks:
        for address in addresses:
            for aux in (0, 1):
                report = len(cases) % 3 == 0
                value = (len(cases) * 37 + 0x53) & 255
                if address < 0xc00:
                    page = address >= 0x800
                    enabled = bool(mask & (0x10 if page else 0x20)) and (not aux or bool(mask & 8))
                    status = (0x82 if mask & 8 else 0x42) + page * 32 + aux * 8
                else:
                    page = address >= 0x4000
                    enabled = bool(mask & (0x40 if page else 0x80)) and (not aux or bool(mask & 4))
                    status = 0xc4 + page * 32 + aux * 8
                status = status + report if enabled else 0
                if enabled:
                    used_status.add(status)
                cases.append((address << 26) | (mask << 18) | (status << 10) |
                             (value << 2) | (aux << 1) | report)
                # Host installs the mask at this held report, then the CPU reads
                # and writes the selected display byte before its completion report.
                program.extend((0xa9, mask, 0x8d, 0x7d, 0xc0,
                                0x8d, 0x05 if aux else 0x04, 0xc0,
                                0xad, address & 255, address >> 8,
                                0xa9, value, 0x8d, address & 255, address >> 8,
                                0xa9, 0xee, 0x8d, 0x7d, 0xc0))
    program.extend((0x4c, 0x00, 0x60))
    assert 0x6000 + len(program) < 0xc000
    memory = bytearray(262144)
    memory[0x6000:0x6000 + len(program)] = program
    memory[0x23a62:0x23a65] = bytes.fromhex('4c0060')
    memory[0x27ffc:0x27ffe] = bytes.fromhex('62fa')
    image = WORK / 'display-capture.hex'
    image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "little"):04x}\n'
                             for i in range(0, len(memory), 2)), encoding='ascii')
    case_image = WORK / 'display-capture-cases.hex'
    case_image.write_text(''.join(f'{value:012x}\n' for value in cases), encoding='ascii')

    # These are the eight main/aux, page-1/page-2 text and HiRes handlers.
    targets = {0x42: 0x30a8, 0x62: 0x30b2, 0x82: 0x30a8, 0xa2: 0x30b2,
               0x8a: 0x30bc, 0xaa: 0x30c6, 0xc4: 0x30d0, 0xe4: 0x30da,
               0xcc: 0x30e4, 0xec: 0x30ee}
    originals, dispatch = [], {}
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        original = path.read_bytes()
        originals.append(path)
        dispatch[driver] = {}
        for status in sorted(used_status):
            offset = 0x28a6 + status * 4
            assert original[offset:offset+2] == bytes.fromhex('4efa')
            target = offset + 2 + int.from_bytes(original[offset+2:offset+4], 'big', signed=True)
            expected = targets[status & 0xfe] + (0x50 if status & 1 else 0)
            assert target == expected, (driver, hex(status), hex(target), hex(expected))
            dispatch[driver][f'{status:02x}'] = f'{target:04x}'

    bench = ROOT / 'tools/tb_display_capture.sv'
    binary = WORK / 'display-capture.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_display_capture', '-o', linux(binary),
         linux(bench), *map(linux, sources)])
    command = ['vvp', linux(binary), '+image=' + linux(image),
               '+cases=' + linux(case_image), f'+count={len(cases)}']
    output = run(command)
    delayed = run([*command, '+latency=73'])
    control = run_process([*command, '+hires-control'])
    assert control.returncode != 0 and 'display mismatch case=176 ' in control.stdout, control.stdout + control.stderr
    print('PASS missing HiRes control rejected; both original driver dispatch tables match')
    record = {'result': output, 'delayed_memory': delayed, 'control': control.stdout,
              'original_dispatch': dispatch, 'cases': len(cases),
              'scope': 'Synthetic CPU stores and real host register ACKs; original dispatch bytes checked, Macintosh renderer not executed',
              'sha256': {str(p): sha(p) for p in [*sources, *originals, bench, Path(__file__), image, case_image]}}
    (WORK / 'display-capture.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
