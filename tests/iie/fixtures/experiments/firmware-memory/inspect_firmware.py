#!/usr/bin/env python3
"""Inspect Startup 2.2.1; keep decoded payloads only in ignored local storage."""

import argparse
import hashlib
import importlib.util
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPECTED = "04eaa7546e7fa426f9c07dea5f193de75fb172d83d29dd362d1954b3385266c9"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def initialized_world(code):
    # CODE 7 $5e-$102: sparse copy records and variable-length integers.
    base = 0x1AE
    size, version, reserved, packed, reloc = struct.unpack_from(">IHHII", code, base)
    assert version == 1 and reserved == 0 and size == 0x595E
    world = bytearray(size)
    cursor, destination = base + packed, 0
    records = []
    repeat = 1

    def integer():
        nonlocal cursor, repeat
        value = code[cursor]
        cursor += 1
        if value < 0x80:
            return value
        if value < 0xC0:
            length, value = 1, value & 0x3F
        elif value < 0xE0:
            length, value = 2, value & 0x1F
        elif value < 0xF0:
            length, value = 4, 0
        else:
            repeat = integer()
            return integer()
        for _ in range(length):
            value = value * 256 + code[cursor]
            cursor += 1
        return value

    while True:
        control = code[cursor]
        cursor += 1
        repeat = 1
        count = (control & 15) * 2 if control & 15 else integer()
        if not count:
            break
        skip = (control >> 4) * 2 if control >> 4 else integer()
        for _ in range(repeat):
            destination += skip
            assert destination + count <= size
            records.append({"code7_offset": cursor, "a5_offset": destination - size,
                            "count": count})
            world[destination:destination + count] = code[cursor:cursor + count]
            cursor += count
            destination += count
    packed_end = cursor
    cursor, destination = base + reloc, 0
    relocation_offsets = []
    while True:
        repeat = 1
        delta = code[cursor]
        cursor += 1
        if delta >= 0x80:
            delta = ((delta & 0x7F) << 8) | code[cursor]
            cursor += 1
        elif delta == 0:
            delta = code[cursor]
            cursor += 1
            if delta == 0:
                break
            if delta >= 0x80:
                delta = int.from_bytes(code[cursor - 1:cursor + 3], "big")
                cursor += 3
            else:
                repeat = delta
                delta = integer()
        for _ in range(repeat):
            destination += delta * 2
            assert 0 <= destination <= size - 4
            relocation_offsets.append(destination - size)
    return bytes(world), {"size_below_a5": size, "packed_offset": base + packed,
                          "relocation_offset": base + reloc, "packed_end": packed_end,
                          "relocation_a5_offsets": relocation_offsets,
                          "copy_records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fork", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    if args.export:
        local = (ROOT / "local/experiments/firmware-memory").resolve()
        assert args.export.resolve().is_relative_to(local), "Export must stay task-local"
        args.export.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "resource_inspector", ROOT / "fixtures/research/software-bringup/inspect_resources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fork = args.fork.read_bytes()
    assert sha(fork) == EXPECTED, "This inspector is pinned to original Startup 2.2.1"
    entries = list(module.resources(fork))
    lookup = {(m["type"], m["id"]): p for m, p in entries}
    world, initialization = initialized_world(lookup["CODE", 7])
    key = world[1:1 + world[0]]
    assert key == b"DoubleX"
    result = {"resource_fork_sha256": sha(fork), "resource_fork_bytes": len(fork),
              "a5_initialization": initialization, "key_a5_offset": -0x595E,
              "key": key.decode("ascii"), "resources": []}
    assert all(offset >= -0x5956 for offset in initialization["relocation_a5_offsets"])
    result["provenance"] = []
    paths = [ROOT / "local/software/Apple-IIe-Card-221-image.sit",
             ROOT / "local/experiments/firmware-memory/v221/Apple IIe Card 2.2.1.image",
             args.fork, args.fork.with_suffix(""), Path(__file__),
             Path(__file__).with_name("reproduce.ps1"),
             Path(spec.origin), ROOT / "local/experiments/firmware-memory/rb/rb-cli.exe",
             Path("C:/Users/Elle/Downloads/mame0289b_x64/unidasm.exe")]
    for path in paths:
        data = path.read_bytes()
        result["provenance"].append({"path": str(path.resolve()),
                                     "bytes": len(data), "sha256": sha(data)})
    for meta, raw in entries:
        kind, rid = meta["type"], meta["id"]
        if kind not in {"CODE", "Monx", "Conf", "CNxx", "C8xx", "CNmc"}:
            continue
        item = dict(meta, sha256=sha(raw))
        if kind == "Monx" or (kind == "Conf" and rid != 1000):
            decoded = (bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
                       if kind == "Monx" else raw)
            tag, dest, count = struct.unpack_from("<HHH", decoded)
            payload = decoded[6:6 + count]
            item.update(descriptor_hex=decoded[:6].hex(" "), tag=tag,
                        destination=dest, count=count, end_inclusive=dest + count - 1,
                        decoded_sha256=sha(decoded), payload_sha256=sha(payload),
                        available_payload_bytes=len(payload),
                        length_delta=len(decoded) - count - 6)
            if kind == "Monx":
                item["duplicate_bitmap_byte"] = decoded[3]
                item["duplicate_bitmap_bit"] = decoded[2] >> 5
            if count == 6:
                item["vector_words_le"] = list(struct.unpack("<3H", payload))
            if kind == "Monx" and rid == 2606:
                item["tail_vector_words_le"] = list(struct.unpack("<3H", payload[-6:]))
            if args.export:
                (args.export / f"{kind}_{rid}.decoded.bin").write_bytes(decoded)
                (args.export / f"{kind}_{rid}.payload.bin").write_bytes(payload)
        result["resources"].append(item)
    if args.export:
        (args.export / "a5-initialized-unrelocated.bin").write_bytes(world)
    args.json.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n",
                         encoding="ascii")


if __name__ == "__main__":
    main()
