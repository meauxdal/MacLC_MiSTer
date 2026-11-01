#!/usr/bin/env python3
"""Inspect an extracted classic Mac resource fork without changing it."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


def resources(blob):
    def read(fmt, offset):
        return struct.unpack_from(">" + fmt, blob, offset)

    data, resource_map, data_size, map_size = read("4I", 0)
    assert data + data_size <= len(blob)
    assert resource_map + map_size <= len(blob)
    types, names = read("2H", resource_map + 24)
    types += resource_map
    names += resource_map
    count = read("H", types)[0] + 1
    for index in range(count):
        kind, count_minus_one, references = read("4sHH", types + 2 + index * 8)
        for entry in range(count_minus_one + 1):
            offset = types + references + entry * 12
            resource_id, name_offset = read("hH", offset)
            attributes = blob[offset + 4]
            start = data + int.from_bytes(blob[offset + 5:offset + 8], "big")
            size = read("I", start)[0]
            assert data <= start and start + 4 + size <= data + data_size
            name = None
            if name_offset != 0xFFFF:
                name_start = names + name_offset
                length = blob[name_start]
                name = blob[name_start + 1:name_start + 1 + length].decode("mac_roman")
            yield {
                "type": kind.decode("mac_roman"),
                "id": resource_id,
                "name": name,
                "attributes": attributes,
                "fork_offset": start + 4,
                "size": size,
            }, blob[start + 4:start + 4 + size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fork", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    blob = args.fork.read_bytes()
    result = {"source": str(args.fork), "size": len(blob),
              "sha256": hashlib.sha256(blob).hexdigest(), "resources": []}
    for metadata, payload in resources(blob):
        metadata["sha256"] = hashlib.sha256(payload).hexdigest()
        if metadata["type"] == "vers":
            metadata["hex"] = payload.hex()
        if metadata["type"] == "STR#":
            strings = []
            offset = 2
            for _ in range(int.from_bytes(payload[:2], "big")):
                size = payload[offset]
                strings.append(payload[offset + 1:offset + 1 + size].decode("mac_roman"))
                offset += 1 + size
            metadata["strings"] = strings
        result["resources"].append(metadata)
        if args.export and metadata["type"] in {"CODE", "Conf", "Monx", "CNxx", "C8xx"}:
            args.export.mkdir(parents=True, exist_ok=True)
            (args.export / (metadata["type"].strip() + "_" + str(metadata["id"]) + ".bin")).write_bytes(payload)
    text = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if args.json:
        args.json.write_text(text, encoding="ascii")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
