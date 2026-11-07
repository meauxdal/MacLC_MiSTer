#!/usr/bin/env python3
"""Boot the original Disk II P5 ROM on the card CPU from a WOZ image through the IWM frontend and backend."""
import json
import sys
import subprocess
from pathlib import Path

from prepare_runtime import ROOT, RTL, WORK, runtime_sources, sha
from check_runtime import linux
import woz_media

WOZ = [RTL / 'woz/flux_drive.v', RTL / 'woz/woz_floppy_controller.sv', RTL / 'woz/woz_cell525.sv',
       RTL / 'woz/woz_bram.sv']


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    monitor = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    # Original "5.25 Disk" slot 6 firmware: CNxx 5632 ($C600, Disk II ID bytes) and Monx 5632 ($C800 upload).
    p5 = ROOT / 'local/experiments/startup-protocol/code/CNxx_5632.bin'
    c8 = ROOT / 'local/experiments/firmware-memory/decoded/Monx_5632.decoded.bin'
    rom, boot_rom, c8_upload = monitor.read_bytes(), p5.read_bytes(), c8.read_bytes()
    assert len(rom) == 16384 and len(boot_rom) == 256
    assert boot_rom[:8] == bytes.fromhex('a220a000a203863c'), 'not the slot 6 Cn page'
    # Monx header: CPU address, card offset from $20000, length.
    assert c8_upload[:4] == bytes.fromhex('00c800f0')
    # Length field is the full $0800 window; the decoded body stops 12 bytes short (rest reads 0).
    assert len(c8_upload) - 6 <= int.from_bytes(c8_upload[4:6], 'little') == 0x800

    # Card memory: monitor ROM at $C000, vectors at $27FFA, slot 6 Cn page at $2C600, its C8 page at $2F000.
    memory = bytearray(262144)
    memory[0x20000:0x24000] = rom
    memory[0x27ffa:0x28000] = rom[0x3ffa:0x4000]
    # The reset pull reads $23FFA before the monitor is active; start both copies at $C600.
    memory[0x23ffc:0x23ffe] = memory[0x27ffc:0x27ffe] = bytes.fromhex('00c6')
    memory[0x2c600:0x2c700] = boot_rom
    memory[0x2f000:0x2f000 + len(c8_upload) - 6] = c8_upload[6:]
    image = WORK / 'disk-boot.hex'
    image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "little"):04x}\n'
                             for i in range(0, len(memory), 2)), encoding='ascii')

    # T0S0: one sector; $0801 LDX $2B, LDA $C088,X (motor off), JMP $0806. Rest is pattern data.
    boot = bytearray(woz_media.sector_data(0, 0))
    boot[:9] = bytes.fromhex('01a62bbd88c04c0608')
    # --control puts a different byte $80 on the disk than the check expects.
    control = '--control' in sys.argv
    # --drive2 boots the same image through the second drive's unit.
    drive2 = '--drive2' in sys.argv
    plusargs = [a for a in sys.argv[1:] if a not in ('--control', '--drive2')]
    on_disk = bytearray(boot)
    if control:
        on_disk[0x80] ^= 0xFF
    disk = WORK / 'disk-boot-woz.hex'
    disk.write_text('\n'.join(f'{b:02x}' for b in woz_media.build_woz(bytes(on_disk))) + '\n', encoding='ascii')

    sources = list(dict.fromkeys([*runtime_sources(), RTL / 'card_iwm_backend.sv', *WOZ]))
    bench = ROOT / 'tools/tb_disk_boot.sv'
    binary = WORK / 'tb_disk_boot.vvp'
    out = WORK / 'disk-boot.txt'
    out.unlink(missing_ok=True)
    subprocess.run(['iverilog', '-g2012', '-s', 'tb_disk_boot', '-o', linux(binary), linux(bench),
                    *map(linux, sources)], check=True)
    result = subprocess.run(['vvp', '-n', linux(binary), f'+image={linux(image)}', f'+disk={linux(disk)}',
                             f'+out={linux(out)}', *(['+drive2'] if drive2 else []), *plusargs], capture_output=True, text=True, timeout=14400)
    print(result.stdout if plusargs else result.stdout[-3000:], result.stderr[-2000:])
    if result.returncode or 'DONE' not in result.stdout:
        raise SystemExit('FAIL simulation')

    lines = out.read_text(encoding='ascii').split()
    fields = dict(zip(lines[0:12:2], lines[1:12:2]))
    page = bytes(int(b, 16) for b in lines[12:])
    if page != boot:
        bad = [i for i in range(256) if page[i] != boot[i]]
        if control and bad == [0x80]:
            print('PASS control: the $0800 check rejects one changed byte at $0880')
            return
        raise SystemExit(f'FAIL $0800 page differs at {bad[:16]}')
    if control:
        raise SystemExit('FAIL control: changed disk byte was not detected')
    if fields['MOTOR_ON_TRAPS'] != '1' or fields['SLOT'] != '60' or fields['TRACK_ID'] != '0':
        raise SystemExit(f'FAIL {fields}')
    record = {'fields': fields, 'stdout': result.stdout[-3000:],
              'scope': 'Original slot 6 firmware (CNxx/Monx 5632) and monitor ROM on the card CPU; synthetic host '
                       f'ACKs motor traps; drive {2 if drive2 else 1} (select inverted for drive 2), read-only WOZ, '
                       'no DOS beyond T0S0',
              'sha256': {str(p): sha(p) for p in [*sources, monitor, p5, c8, bench, Path(__file__),
                                                  ROOT / 'tools/woz_media.py']}}
    (WORK / ('disk-boot-drive2.json' if drive2 else 'disk-boot.json')).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(f'PASS disk boot{" (drive 2)" if drive2 else ""}: original slot 6 firmware recalibrated to track 0, read T0S0 into $0800 and ran it; '
          f'motor on at {fields["MOTOR_ON_MS"]} ms, boot sector at {fields["BOOT_MS"]} ms, '
          f'{fields["BLOCKS"]} image blocks read')


if __name__ == '__main__':
    main()
