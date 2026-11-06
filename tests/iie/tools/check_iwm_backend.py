#!/usr/bin/env python3
"""Check the IIe card 5.25 drive backend: WOZ mount, reads, stepping, holdover, write and write-back."""
import json
import subprocess

from prepare_runtime import ROOT, WORK, RTL, sha
from check_runtime import linux
import woz_media

SOURCES = [RTL / 'card_iwm_backend.sv', RTL / 'woz/flux_drive.v', RTL / 'woz/woz_floppy_controller.sv',
           RTL / 'woz/woz_cell525.sv', RTL / 'woz/woz_bram.sv']
BENCH = ROOT / 'tools/tb_iwm_backend.sv'
SALT = 100


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    image = woz_media.build_woz()
    hex_path = WORK / 'iwm-backend.hex'
    hex_path.write_text('\n'.join(f'{b:02x}' for b in image) + '\n', encoding='ascii')
    # CPU cycles at 1.0205 MHz to 32.5 MHz clocks.
    write_path = WORK / 'iwm-backend-write.txt'
    write_path.write_text(''.join(f'{b:02x} {round(c * 32.5 / 1.0205)}\n'
                                  for b, c in woz_media.write_schedule(2, SALT)), encoding='ascii')
    binary = WORK / 'tb_iwm_backend.vvp'
    out = WORK / 'iwm-backend-capture.txt'
    subprocess.run(['iverilog', '-g2012', '-s', 'tb_iwm_backend', '-o', linux(binary), linux(BENCH),
                    *map(linux, SOURCES)], check=True)
    result = subprocess.run(['vvp', '-n', linux(binary), f'+image={linux(hex_path)}', f'+out={linux(out)}',
                             f'+write={linux(write_path)}'], capture_output=True, text=True, timeout=7200)
    if result.returncode or 'DONE' not in result.stdout:
        print(result.stdout[-4000:], result.stderr[-2000:])
        raise SystemExit('FAIL simulation')

    streams, current, summary = {}, None, ''
    for line in out.read_text(encoding='ascii').split('\n'):
        if line[:1] in ('T', 'W'):
            current = line
            streams[current] = bytearray()
        elif line.startswith('BLOCKS'):
            summary = line
        elif line:
            streams[current].append(int(line, 16))
    record = {'summary': summary, 'tracks': {}}
    for name, stream in streams.items():
        track = int(name[1:])
        salt = SALT if name[0] == 'W' else 0
        found = woz_media.sectors(bytes(stream))
        wrong_track = sorted({t for t, _ in found} - {track})
        sectors = sorted(s for t, s in found if t == track)
        bad = [s for s in sectors if found[(track, s)] != woz_media.sector_data(track + salt, s)]
        record['tracks'][name] = {'nibbles': len(stream), 'sectors': sectors, 'bad': bad,
                                  'other_tracks': wrong_track}
        print(f'{name}: {len(sectors)} sectors decoded, bad={bad}, other tracks={wrong_track}')
        if len(sectors) != 16 or bad or wrong_track:
            raise SystemExit(f'FAIL {name}')
    print(summary)
    fields = summary.split()
    written, reloaded = int(fields[2]), int(fields[-1])
    if written != 13 or reloaded < 16:
        raise SystemExit('FAIL write-back or reload block counts')
    record['sha256'] = {str(p): sha(p) for p in [*SOURCES, BENCH, ROOT / 'tools/woz_media.py']}
    (WORK / 'iwm-backend.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS IWM backend: WOZ mount, 16 sectors on tracks 0 and 2, stepping, holdover, track write, '
          'write-back and reload from the image')


if __name__ == '__main__':
    main()
