#!/usr/bin/env python3
"""Inspect an extracted IIe Startup resource fork without writing payloads."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("resource_fork", type=Path)
args = parser.parse_args()
data = args.resource_fork.read_bytes()
assert sha256(data) == "31b26a51ee52d026a945b4ecc52efeb8cdf0a5a921f3e77398210bb717374799"
data_offset, map_offset, data_size, map_size = struct.unpack_from(">4I", data)
type_list = map_offset + struct.unpack_from(">H", data, map_offset + 24)[0]
name_list = map_offset + struct.unpack_from(">H", data, map_offset + 26)[0]
type_count = struct.unpack_from(">H", data, type_list)[0] + 1
resources = {}
for i in range(type_count):
    kind, count, refs = struct.unpack_from(">4sHH", data, type_list + 2 + 8 * i)
    kind = kind.decode("mac_roman")
    for j in range(count + 1):
        ref = type_list + refs + 12 * j
        rid, name_offset = struct.unpack_from(">hH", data, ref)
        offset = data_offset + int.from_bytes(data[ref + 5:ref + 8], "big")
        size = struct.unpack_from(">I", data, offset)[0]
        assert offset + 4 + size <= data_offset + data_size
        name = ""
        if name_offset != 0xffff:
            n = name_list + name_offset
            name = data[n + 1:n + 1 + data[n]].decode("mac_roman")
        payload = data[offset + 4:offset + 4 + size]
        resources[kind, rid] = (payload, {
            "type": kind, "id": rid, "name": name,
            "fork_offset": offset + 4, "bytes": size,
            "sha256": sha256(payload),
        })

selected = [meta for (kind, rid), (payload, meta) in resources.items()
            if kind in ("CODE", "Monx", "CNmc", "vers")]
windows = {("CODE", 1): [(0x4c, 12), (0x3666, 16), (0x38a2, 44),
                            (0x3906, 34), (0x3968, 68), (0x3a92, 66),
                            (0xaca, 70)],
           ("CODE", 2): [(0x476, 44), (0x1728, 56)]}
fragments = []
for key, ranges in windows.items():
    payload = resources[key][0]
    for offset, size in ranges:
        fragments.append({"type": key[0], "id": key[1],
                          "offset": hex(offset),
                          "hex": payload[offset:offset + size].hex(" ")})

encoded = resources["Monx", 2606][0]
key = b"DoubleX"
decoded = bytes(value ^ key[i % len(key)] for i, value in enumerate(encoded))
rom = decoded[6:]
speed_pattern = bytes.fromhex("a9 04 2c 2b c0")
version = resources["vers", 1][0]
print(json.dumps({
    "resource_fork_bytes": len(data), "resource_fork_sha256": sha256(data),
    "resource_count": len(resources),
    "version_string": version[7:7 + version[6]].decode("mac_roman"),
    "resources": selected,
    "instruction_windows": fragments,
    "monitor": {"transform": "repeating XOR DoubleX, starting at resource byte 0",
                "decoded_header": decoded[:6].hex(" "),
                "decoded_resource_sha256": sha256(decoded),
                "payload_bytes": len(rom), "payload_sha256": sha256(rom),
                "speed_mask_pattern_payload_offset": hex(rom.index(speed_pattern)),
                "speed_mask_pattern_hex": speed_pattern.hex(" "),
                "identification_under_C000_mapping": {
                    hex(address): hex(rom[address - 0xc000])
                    for address in (0xfbb3, 0xfbc0, 0xfbdd, 0xfbbe)}},
}, indent=2, ensure_ascii=True))
