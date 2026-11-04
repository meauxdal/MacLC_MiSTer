#!/usr/bin/env python3
"""Exercise the original software-slot capture and reply protocol."""
import json
from pathlib import Path

from prepare_runtime import ROOT, WORK, runtime_sources, sha
from check_runtime import linux, run, run_process


def main():
    sources = runtime_sources()
    program = bytearray()
    index = 0
    for slot in (1, 2, 3, 4, 5, 7):
        for offset in range(16):
            address = 0xc080 + slot * 16 + offset
            value = (index * 37 + 83) & 255
            program.extend((0xa9, value, 0x8d, address & 255, address >> 8,
                            0xad, address & 255, address >> 8,
                            0x8d, 0x00, 0x02, 0x8d, 0x7d, 0xc0))
            index += 1
    program.extend((0x4c, 0x00, 0x60))
    memory = bytearray(262144)
    memory[0x6000:0x6000 + len(program)] = program
    memory[0x23a62:0x23a65] = bytes.fromhex('4c0060')
    memory[0x27ffc:0x27ffe] = bytes.fromhex('62fa')
    image = WORK / 'slot-io.hex'
    image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "little"):04x}\n'
                             for i in range(0, len(memory), 2)), encoding='ascii')
    originals = []
    for driver in (5, 6):
        path = ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin'
        data = path.read_bytes()
        originals.append(path)
        for status, expected in ((8, 0xb10), (9, 0xb36)):
            entry = 0x28a6 + status * 4
            assert data[entry:entry+2] == bytes.fromhex('4efa')
            assert entry + 2 + int.from_bytes(data[entry+2:entry+4], 'big', signed=True) == expected
        assert data[0xb2c:0xb30] == bytes.fromhex('4ea80040')
        assert data[0xb52:0xb56] == bytes.fromhex('4ea8003c')

    # The installed Disk II host stub uses +$19 for read replies and +$0C for ACK.
    metadata = ROOT / 'local/experiments/startup-protocol/resources.json'
    fork = ROOT / 'local/experiments/startup-protocol/app221/IIe Startup.rsrc'
    item = next(r for r in json.loads(metadata.read_text())['resources']
                if r['type'] == 'CNmc' and r['id'] == 5632)
    payload = fork.read_bytes()[item['fork_offset']:item['fork_offset'] + item['size']]
    assert payload[0x6c:0x7a] == bytes.fromhex('1973201800194e75422c000c4e75')

    bench = ROOT / 'tools/tb_slot_io.sv'
    binary = WORK / 'slot-io.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_slot_io', '-o', linux(binary),
         linux(bench), *map(linux, sources)])
    command = ['vvp', linux(binary), '+image=' + linux(image)]
    output = run(command)
    delayed = run([*command, '+latency=73'])
    controls = {}
    for name, failure in (('reply-control', 'slot reply mismatch index=0 '),
                          ('release-control', 'slot IO fault/watchdog cause=8')):
        result = run_process([*command, '+' + name])
        assert result.returncode != 0 and failure in result.stdout, result.stdout + result.stderr
        controls[name] = result.stdout
        print('PASS rejected ' + name)
    record = {'result': output, 'delayed_memory': delayed, 'controls': controls,
              'scope': 'Synthetic CPU and host service, original dispatch/stub bytes checked; no complete peripheral emulation or disk boot',
              'sha256': {str(p): sha(p) for p in [*sources, *originals, metadata, fork, bench, Path(__file__), image]}}
    (WORK / 'slot-io.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
