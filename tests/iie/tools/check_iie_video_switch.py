#!/usr/bin/env python3
"""Execute the original LC display switch on TG68K and PseudoVIA."""
from pathlib import Path
import subprocess

from check_runtime import linux, run


def main():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    work = root / 'local/experiments/iie-video-switch'
    work.mkdir(parents=True, exist_ok=True)
    code = (root / 'local/experiments/version-check/2.2.2d1-CODE-1.bin').read_bytes()
    # Pin the original LC register operations, including BFINS and both guards.
    assert code[0x4216:0x4252].hex() == (
        '43f950f260004a6e000a671608e9000000016600008810290010'
        '020000075200601208a900000001677210290010020000075300efe9014300106060')
    memory = bytearray(0x40000)
    memory[:8] = bytes.fromhex('0001000000000100')
    program = bytes.fromhex('2a7c000040003b7c0013ec42')
    for entering in (1, 1, 0, 0):
        program += bytes.fromhex('2f3c') + entering.to_bytes(4, 'big')
        program += bytes.fromhex('4eb900024202588f13fc005a00000300')
    program += bytes.fromhex('60fe')
    memory[0x100:0x100 + len(program)] = program
    memory[0x20000:0x20000 + len(code)] = code
    image = work / 'switch.hex'
    image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "big"):04x}\n'
                             for i in range(0, len(memory), 2)), encoding='ascii')
    sources = [repo / 'rtl/tg68k' / name for name in
               ('TG68K_Pack.sv', 'TG68K_ALU.v', 'TG68KdotC_Kernel.v', 'tg68k.v')]
    bench = root / 'tools/tb_iie_video_switch.sv'
    original = repo / 'rtl/pseudovia.sv'
    for control in (False, True):
        source = original
        if control:
            source = work / 'pseudovia_control.sv'
            text = original.read_text()
            assert "monitor_id[3:0], video_config[2:0]" in text
            source.write_text(text.replace('monitor_id[3:0], video_config[2:0]',
                                           "monitor_id[3:0], 3'b000"), encoding='utf-8')
        binary = work / ('control.vvp' if control else 'switch.vvp')
        run(['iverilog', '-g2012', '-s', 'tb_iie_video_switch', '-o', linux(binary),
             linux(bench), linux(source), *map(linux, sources)])
        for mode in range(4):
            command = ['wsl', '--exec', 'vvp', linux(binary), '+image=' + linux(image), f'+mode={mode}']
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            if control:
                expected = 'format=7 initial=0' if mode == 0 else f'format=1 initial={mode}'
                assert result.returncode and expected in result.stdout, result.stdout + result.stderr
            else:
                assert result.returncode == 0, result.stdout + result.stderr
                print(result.stdout, end='')
        if control:
            print('PASS zero-format readback control rejected for all four initial formats')


if __name__ == '__main__':
    main()
