#!/usr/bin/env python3
"""Check actual overlay pixels and save a preview from the simulation."""
import json
import shlex
import struct
import subprocess
import zlib
from prepare import HERE, WORK, sha


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def run(command):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    sources = [HERE / 'tb_overlay.sv', HERE / 'iie_status_overlay.sv']
    binary = WORK / 'overlay.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_overlay', '-o', linux(binary), *map(linux, sources)])
    raw = WORK / 'overlay.ppm'
    result = run(['vvp', linux(binary), '+output=' + linux(raw)])
    run(['verilator', '--lint-only', '-Wall', '--top-module', 'iie_status_overlay', linux(sources[1])])
    header, data = raw.read_bytes().split(b'255\n', 1)
    assert header == b'P6\n512 384\n' and len(data) == 512 * 384 * 3
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    scanlines = b''.join(b'\0' + data[row * 1536:(row + 1) * 1536] for row in range(384))
    png = WORK / 'status-preview.png'
    png.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', 512, 384, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))
    record = {'scope': 'Simulation of real overlay pixels with test status; not a hardware capture',
        'result': result.stdout.strip(), 'preview': str(png), 'preview_sha256': sha(png),
        'inputs_sha256': {str(p): sha(p) for p in [*sources, HERE / 'check_overlay.py']}}
    (HERE / 'overlay-results.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print(result.stdout.strip())


if __name__ == '__main__':
    main()
