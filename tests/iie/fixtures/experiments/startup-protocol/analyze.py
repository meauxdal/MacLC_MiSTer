#!/usr/bin/env python3
"""Summarize original Startup discovery and Conf access sites; no guest execution."""

import argparse
import hashlib
import importlib.util
import json
import re
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPECTED = "04eaa7546e7fa426f9c07dea5f193de75fb172d83d29dd362d1954b3385266c9"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def discovered_base(error, slot, machine):
    if error:
        return 0
    if not slot:
        return 0xFEE00000 if machine == 19 else 0
    value = (((slot | 0xF0) << 4) | slot) & 0xFFFF
    return ((value >> 12) | (value << 20)) & 0xFFFFFFFF


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fork", type=Path)
    parser.add_argument("unidasm", type=Path)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blob = args.fork.read_bytes()
    assert digest(blob) == EXPECTED, "Expected unmodified Startup 2.2.1"
    spec = importlib.util.spec_from_file_location(
        "inspector", ROOT / "fixtures/research/software-bringup/inspect_resources.py")
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    resources = {(m["type"], m["id"]): (m, b) for m, b in inspector.resources(blob)}
    args.scratch.mkdir(parents=True, exist_ok=True)
    selected = []
    for key in [("CODE", 0), ("CODE", 1), ("CODE", 2)] + [
            ("Conf", i) for i in range(1000, 1005)]:
        meta, data = resources[key]
        selected.append({**meta, "sha256": digest(data)})
        (args.scratch / f"{key[0]}_{key[1]}.bin").write_bytes(data)
    conf = args.scratch / "Conf_1000.bin"
    disassembly = subprocess.check_output(
        [str(args.unidasm.resolve()), str(conf.resolve()), "-arch", "m68020"],
        text=True)
    sites = []
    for line in disassembly.splitlines():
        match = re.match(r"([0-9a-f]+):\s+((?:[0-9a-f]{4}\s+)+)(.*)", line)
        if match and ",A4)" in match[3]:
            sites.append({"pc": f"{int(match[1], 16):03X}",
                          "instruction": match[3].strip()})
    descriptors = []
    for rid in range(1001, 1005):
        data = resources["Conf", rid][1]
        descriptors.append({"id": rid, "header": data[:6].hex(" "),
                            "destination_le16": struct.unpack_from("<H", data, 2)[0],
                            "count_le16": struct.unpack_from("<H", data, 4)[0],
                            "payload_bytes": len(data) - 6})
    jump = resources["CODE", 0][1]
    jump_targets = {}
    for address in (0xAA, 0xB2, 0xD2, 0x1DA):
        offset = 16 + address - 2 - 0x20
        target, opcode, segment, trap = struct.unpack_from(">4H", jump, offset)
        assert opcode == 0x3F3C and trap == 0xA9F0
        jump_targets[f"A5+{address:X}"] = {
            "segment": segment, "resource_offset": f"{target + 4:X}"}
    result = {
        "source": args.fork.as_posix(), "bytes": len(blob), "sha256": digest(blob),
        "unidasm_sha256": digest(args.unidasm.read_bytes()),
        "resources": selected, "conf_descriptors": descriptors,
        "jump_targets": jump_targets,
        "slot_bases_machine_19": {f"{s:X}": f"{discovered_base(0, s, 19):08X}"
                                  for s in (0, 9, 10, 14, 15)},
        "conf_access_sites": sites,
    }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n",
                           encoding="ascii")


if __name__ == "__main__":
    main()
