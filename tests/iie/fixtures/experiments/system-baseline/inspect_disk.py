#!/usr/bin/env python3
"""Read-only HDA inventory using the supplied Rusty Backup and resource reader."""

import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "fixtures/research/software-bringup"))
from inspect_resources import resources


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rb", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    def rb(*words):
        result = subprocess.run([str(args.rb.resolve()), *map(str, words)],
                                capture_output=True, check=True)
        return result.stdout.decode("utf-8-sig")

    disk = args.image.read_bytes()
    u16 = lambda offset: struct.unpack_from(">H", disk, offset)[0]
    u32 = lambda offset: struct.unpack_from(">I", disk, offset)[0]
    cstr = lambda offset, size: disk[offset:offset + size].split(b"\0")[0].decode("mac_roman")
    assert disk[:2] == b"ER" and disk[512:514] == b"PM"
    block_size = u16(2)
    assert block_size == 512
    partitions = []
    for index in range(1, u32(516) + 1):
        offset = index * block_size
        assert disk[offset:offset + 2] == b"PM"
        start, count = u32(offset + 8), u32(offset + 12)
        assert (start + count) * block_size <= len(disk)
        partitions.append(dict(map_entry=index, name=cstr(offset + 16, 32),
                               type=cstr(offset + 48, 32), start_lba=start,
                               blocks=count, status=f"{u32(offset + 88):08x}"))
    hfs = next(p for p in partitions if p["type"] == "Apple_HFS")
    base = hfs["start_lba"] * block_size
    mdb = base + 1024
    assert disk[mdb:mdb + 2] == b"BD"
    finder_info = [u32(mdb + 92 + i * 4) for i in range(8)]
    result = {
        "schema_version": 1,
        "image": {"path": args.image.as_posix(), "bytes": len(disk),
                  "sha256": digest(disk)},
        "ddr": {"block_size": block_size, "block_count": u32(4),
                "driver_count": u16(16), "driver_start_lba": u32(18),
                "driver_blocks": u16(22), "driver_os_type": u16(24)},
        "partitions": partitions,
        "hfs": {"volume": cstr(mdb + 37, disk[mdb + 36]),
                "attributes_hex": f"{u16(mdb + 10):04x}",
                "allocation_blocks": u16(mdb + 18),
                "allocation_block_bytes": u32(mdb + 20),
                "allocation_start_sector": u16(mdb + 28),
                "free_allocation_blocks": u16(mdb + 34),
                "finder_info": finder_info,
                "blessed_cnid": finder_info[0],
                "bless_query": rb("bless", "show", args.image).strip(),
                "boot_signature_hex": disk[base:base + 2].hex(),
                "boot_blocks_sha256": digest(disk[base:base + 1024]),
                "extents_clump_bytes": u32(mdb + 74),
                "catalog_clump_bytes": u32(mdb + 78),
                "primary_mdb_sha256": digest(disk[mdb:mdb + 512]),
                "alternate_mdb_sha256": digest(disk[-1024:-512]),
                "alternate_blessed_cnid": u32(len(disk) - 1024 + 92),
                "primary_alternate_mdb_equal": disk[mdb:mdb + 512] == disk[base + hfs["blocks"] * 512 - 1024:base + hfs["blocks"] * 512 - 512]},
        "files": [], "directories": [],
        "tools": {"rb_version": rb("--version").strip(),
                  "rb_sha256": digest(args.rb.read_bytes()),
                  "resource_reader_sha256": digest((ROOT / "fixtures/research/software-bringup/inspect_resources.py").read_bytes())},
    }
    tree = json.loads(rb("ls", args.image, "**", "--format", "json"))["result"]
    for index, entry in enumerate(tree):
        path = entry["name"]
        if entry["kind"] == "DIR":
            result["directories"].append(path)
            continue
        out = args.work / f"file-{index:03d}"
        out.mkdir(exist_ok=True)
        archive = out / "forks.hqx"
        rb("get-binhex", args.image, path, archive)
        rb("archive", "extract", archive, out, "--format", "raw")
        name = path.rsplit("/", 1)[1]
        extracted = [p for p in out.iterdir() if p.name != "forks.hqx"
                     and not p.name.endswith(".rsrc")]
        assert len(extracted) == 1
        data = extracted[0].read_bytes()
        fork_path = extracted[0].with_name(extracted[0].name + ".rsrc")
        fork = fork_path.read_bytes() if fork_path.exists() else b""
        record = {"path": path, "type": entry["type_code"],
                  "creator": entry["creator_code"],
                  "data_bytes": len(data), "data_sha256": digest(data),
                  "resource_bytes": len(fork), "resource_sha256": digest(fork)}
        assert len(data) == entry["size"]
        if fork:
            version_records = []
            special = []
            for metadata, payload in resources(fork):
                if metadata["type"] == "vers":
                    n = payload[6]
                    version_records.append({"id": metadata["id"],
                                            "fork_offset": metadata["fork_offset"],
                                            "hex": payload.hex(),
                                            "short": payload[7:7 + n].decode("mac_roman")})
                if name == "System" and metadata["type"] in {"gbly", "ROvr", "boot"}:
                    special.append({**metadata, "sha256": digest(payload)})
            record["versions"] = version_records
            if special:
                record["boot_resources"] = special
        result["files"].append(record)
    rom_path = Path("C:/Workspace/Git/MacLC_MiSTer/releases/boot0.rom")
    rom = rom_path.read_bytes()
    result["lc_rom"] = {
        "path": rom_path.as_posix(), "bytes": len(rom), "sha256": digest(rom),
        "sha1": hashlib.sha1(rom).hexdigest(),
        "header_checksum": rom[:4].hex(),
        "computed_word_sum": f"{sum(struct.unpack('>' + str((len(rom) - 4) // 2) + 'H', rom[4:])) & 0xffffffff:08x}",
    }
    after = digest(args.image.read_bytes())
    assert after == result["image"]["sha256"]
    result["image"]["sha256_after"] = after
    result["image"]["unchanged"] = True
    args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="ascii")
    print(f"Inventoried {len(result['files'])} files; source hash unchanged.")


if __name__ == "__main__":
    main()
