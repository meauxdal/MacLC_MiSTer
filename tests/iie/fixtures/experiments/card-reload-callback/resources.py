#!/usr/bin/env python3
"""Extract hash-checked original callback and alert resources."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FORK = ROOT / 'local/experiments/firmware-memory/app221/IIe Startup.rsrc'
META = ROOT / 'local/experiments/firmware-memory/resources.json'


def load():
    metadata = json.loads(META.read_text())
    blob = FORK.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == metadata['sha256']
    result = {}
    for key in (('CNmc', 6400), ('ALRT', 0x1928)):
        item = next(r for r in metadata['resources'] if (r['type'], r['id']) == key)
        data = blob[item['fork_offset']:item['fork_offset'] + item['size']]
        assert hashlib.sha256(data).hexdigest() == item['sha256']
        result[key[0]] = data
    header = int.from_bytes(result['CNmc'][2:4], 'big')
    assert int.from_bytes(result['CNmc'][header + 2:header + 4], 'big') == 0x68d
    assert len(result['CNmc']) == 0xc08 and len(result['ALRT']) == 12
    return result, [FORK, META, Path(__file__)]


def descriptor(phase):
    data = bytearray([0x5a]) * 64 + bytearray(0x68d) + bytearray([0x5a]) * 64
    if not phase:
        return data
    def put(offset, value, size=4):
        data[64 + offset:64 + offset + size] = value.to_bytes(size, 'big')
    for offset, value, size in (
        (2, 8, 2), (4, 0x360008, 4), (8, 0x2849d8, 4),
        (0x5c4, 0x1928, 2), (0x5c6, 1, 2),
        (0x61a, 0x380040, 4), (0x650, 0x380040, 4),
        (0x674, 0x3806cb, 4), (0x63e, 0x3806ca, 4),
        (0x642, 1, 4), (0x678, 1, 4), (0x660, 0x3907d6, 4), (0x62a, 0x3907ea, 4),
    ):
        put(offset, value, size)
    return data
