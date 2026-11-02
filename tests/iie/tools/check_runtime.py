#!/usr/bin/env python3
"""Check the combined card closure with lint, TG68K launch and native memory."""
import json
import os
from pathlib import Path
import subprocess

from prepare_runtime import MACLC, ROOT, RTL, WORK, prepare, sha


def linux(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:] if path.drive else path.as_posix()


def run_process(command, timeout=60):
    if os.name == 'nt':
        command = ['wsl.exe', '--cd', linux(ROOT), '--exec', *command]
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def run(command):
    try:
        result = run_process(command)
    except subprocess.TimeoutExpired as error:
        for output in (error.stdout, error.stderr):
            if output:
                print(output.decode(errors='replace') if isinstance(output, bytes) else output, end='')
        raise
    print(result.stdout, end='')
    if result.returncode:
        print(result.stderr)
        raise RuntimeError(f'HDL check failed: {command[0]}')
    return result.stdout


def main():
    closure = prepare()
    run(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
         '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module', 'maclc_iie_binding',
         linux(RTL / 'maclc_iie_binding.sv'), *map(linux, closure)])
    bench = ROOT / 'fixtures/experiments/maclc-iie-trial/tb_launch_bus.sv'
    launch_bench = WORK / 'tb_launch.sv'
    launch_bench.write_text(bench.read_text().replace('.por_n(!reset),',
        ".por_n(!reset), .runtime_mode(1'b0),"), encoding='ascii')
    host = [MACLC / 'rtl/tg68k' / name for name in
            ('TG68K_Pack.sv', 'TG68K_ALU.v', 'TG68KdotC_Kernel.v', 'tg68k.v')]
    conf = ROOT / 'local/experiments/firmware-memory/code/Conf_1000.bin'
    program = bytes.fromhex('287cfe000000') + conf.read_bytes()[0xa:0x1c] + bytes.fromhex('13fc005a0000020060fe')
    rom = bytearray(bytes.fromhex('4e71') * 256)
    rom[:8] = bytes.fromhex('0001000000000100')
    rom[0x100:0x100 + len(program)] = program
    image = WORK / 'launch.hex'
    image.write_text(''.join(f'{int.from_bytes(rom[i:i+2], "big"):04x}\n' for i in range(0, len(rom), 2)), encoding='ascii')
    binary = WORK / 'launch.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_launch_bus', '-o', linux(binary),
         linux(launch_bench), *map(linux, closure + host)])
    launch = run(['vvp', linux(binary), '+program=' + linux(image)])
    original = ROOT / 'local/experiments/card-diagnostic-final/tb_binding.sv'
    bench = WORK / 'tb_diagnostic.sv'
    source = original.read_text().replace('    wire diagnostic_boundary, diagnostic_fault;',
        "    wire diagnostic_boundary, diagnostic_fault;\n    wire [271:0] debug_status;\n    wire runtime_mode = 1'b0;")
    source = source.replace('if (status == 5) transact(writing, word_access, offset, value, gap);',
        '''if (status == 5) begin
                if (!writing && !word_access && offset == 1 && value > 0)
                    wait(capture_valid);
                transact(writing, word_access, offset, value, gap);
            end''')
    bench.write_text(source, encoding='ascii')
    controller = RTL / 'sdram.v'
    binary = WORK / 'diagnostic.vvp'
    run(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform', '-o', linux(binary),
         linux(bench), linux(RTL / 'maclc_iie_binding.sv'), *map(linux, closure), linux(controller)])
    diagnostics = []
    for fork in (0, 1):
        diagnostics.append(run(['vvp', linux(binary),
            '+stimulus=' + linux(ROOT / f'local/experiments/card-firmware-overlay/stimulus{fork}.txt'),
            '+expected=' + linux(ROOT / f'local/experiments/card-diagnostic-final/expected{fork}.hex'),
            '+trace=' + linux(WORK / f'diagnostic-{fork}.txt')]))
    binary = WORK / 'runtime.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_runtime', '-o', linux(binary),
         linux(ROOT / 'tools/tb_runtime.sv'), *map(linux, closure)])
    runtime = run(['vvp', linux(binary)])
    record = {'lint': 'pass', 'launch': launch, 'assisted_diagnostic': diagnostics,
              'runtime_smoke': runtime,
              'sha256': {str(p): sha(p) for p in [*closure, RTL / 'maclc_iie_binding.sv', Path(__file__)]}}
    (WORK / 'checks.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS combined runtime checks')


if __name__ == '__main__':
    main()
