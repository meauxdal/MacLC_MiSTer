#!/usr/bin/env python3
"""Check slot expansion selection and the original hardware-stop prefix."""
import json
from pathlib import Path

from prepare_runtime import ROOT, WORK, runtime_sources, sha
from check_runtime import linux, run


def main():
    sources = runtime_sources()
    assets = ROOT / 'local/experiments/startup-protocol/code'
    cn = assets / 'CNxx_4096.bin'
    c8 = assets / 'C8xx_4096.bin'
    cn_data, c8_data = cn.read_bytes(), c8.read_bytes()
    assert cn_data[0x620:0x626] == bytes.fromhex('2c ff cf 20 cc c9')
    assert c8_data[0x1cc:0x1d5] == bytes.fromhex('8e 78 07 ae 5c c0 8e 2b c0')
    memory = bytearray(262144)
    memory[0x2c700:0x2c800] = cn_data[0x600:0x700]
    memory[0x2f800:0x2f800 + len(c8_data)] = c8_data
    memory[0x27ffc:0x27ffe] = bytes.fromhex('20 c7')
    image = WORK / 'slot-rom.hex'
    image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "little"):04x}\n'
                             for i in range(0, len(memory), 2)), encoding='ascii')
    bench = ROOT / 'tools/tb_slot_rom.sv'
    binary = WORK / 'slot-rom.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_slot_rom', '-o', linux(binary),
         linux(bench), *map(linux, sources)])
    output = run(['vvp', linux(binary), '+image=' + linux(image)])
    control = run(['vvp', linux(binary), '+image=' + linux(image), '+control'])
    record = {'result': output, 'control': control,
              'scope': 'Original slot-7 C720-C725 and C9CC-C9D4 prefix; candidate upload geometry; no disk backend or full boot',
              'sha256': {str(p): sha(p) for p in [*sources, cn, c8, bench, Path(__file__)]}}
    (WORK / 'slot-rom.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
