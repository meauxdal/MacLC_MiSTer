#!/usr/bin/env python3
"""Pinned SDRAM producer ranges and an oversized-loader alias witness."""

import hashlib
import json
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
MACLC = Path("C:/Workspace/Git/MacLC_MiSTer")
PINNED = {
    "MacLC.sv": "3bafa309638a9325cbff5401b06402d066b9e8ac2340aafacf14549617a7e1f0",
    "files.qip": "2dfeea36a23f868d079b2361ffc2507f654bd584a530839b8a4155f6234d303d",
    "rtl/addrController_top.v": "b9f619a0378bce1bd057c71645814be26ae46d5222688776dd2987fc51e95f78",
    "rtl/addrDecoder.v": "4714846b53d8338856f98c2073492561325a130a28966161b6f935ee9cc0249d",
    "rtl/floppy_sd.v": "511ab0548c7f4f2d712bdc737b6442b006264ecaca75f01a5383ce3fa0424988",
    "rtl/sdram.v": "953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04",
}
CARD = (0x540000, 0x55FFFF)


def pinned_sources():
    sources = {}
    for name, expected in PINNED.items():
        data = (MACLC / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, f"source changed: {name}"
        sources[name] = data.decode("utf-8")
    return sources


def main():
    sources = pinned_sources()
    evidence = []

    def witness(path, fragment, producer):
        text = sources[path]
        assert text.count(fragment) == 1, fragment
        line = text[:text.index(fragment)].count("\n") + 1
        evidence.append({"producer": producer, "path": path, "line": line, "source": fragment})

    witness("rtl/addrController_top.v", "motherboard_high ? {3'b000, cpuAddr[20:1]}", "motherboard")
    witness("rtl/addrController_top.v", "(23'h100000 + {1'b0, cpu_word})", "SIMM")
    witness("rtl/addrController_top.v", "rom_sdram_word = {5'b10100, cpuAddr[18:1]}", "CPU ROM")
    witness("rtl/addrController_top.v", "23'h580000 + {5'b0, vram_cpu_offset[18:1]}", "VRAM")
    witness("rtl/addrController_top.v", "23'h600000 + {2'b0, dskReadAddrInt[21:1]}", "floppy window")
    witness("MacLC.sv", "dio_a    <= {5'b10100, dio_addr[17:0]}", "HPS ROM")
    witness("MacLC.sv", "24'h600000 + {3'd0, wc_addr[21:1]}", "floppy committer")
    witness("MacLC.sv", ".base_addr(24'h600000)", "floppy loader base")
    witness("MacLC.sv", ".img_base        ( 24'h600000 )", "floppy readback base")
    witness("rtl/floppy_sd.v", "mem_addr <= img_base + pay_word;", "floppy block readback")
    witness("rtl/floppy_sd.v", "mem_addr <= img_base + {3'd0, scan_w};", "floppy checksum scan")
    witness("rtl/floppy_sd.v", "sec_total <= img_size[40:9] + {31'd0, |img_size[8:0]};", "loader size truncation")
    witness("rtl/floppy_sd.v", "(dc42 ? (file_word - DC42_HDR_WORDS) : file_word);", "loader offset")
    witness("rtl/sdram.v", "{ 1'b0, eth_addr[19:8] }", "SDRAM row")
    witness("rtl/sdram.v", "eth_addr[21:20]", "SDRAM bank")
    witness("rtl/sdram.v", "{ eth_addr[22], eth_addr[7:0] }", "SDRAM column")
    witness("MacLC.sv", "VRAM is left uninitialized", "no VRAM seeder")
    witness("MacLC.sv", ".eth_req        ( flp_mem_req )", "retained native client")
    witness("MacLC.sv", ".dl_addr        ( sdram_dladdr_q", "download input closure")
    witness("MacLC.sv", "assign DDRAM_WE = 0;", "DDR inactive")
    ranges = {
        "motherboard_and_mirrors": (0, 0x0FFFFF),
        "SIMM_all_supported_configs": (0x100000, 0x4FFFFF),
        "CPU_ROM_and_HPS_ROM_any_ioctl_address": (0x500000, 0x53FFFF),
        "CPU_VRAM": (0x580000, 0x5BFFFF),
        "floppy_window_and_committer_all_22bit_offsets": (0x600000, 0x7FFFFF),
        "floppy_writer_block_and_checksum": (0x600000, 0x7FFFFF),
        "loader_with_payload_and_padding_within_2MiB": (0x600000, 0x6FFFFF),
    }
    for low, high in ranges.values():
        assert high < CARD[0] or low > CARD[1]
    def pins(word):
        return ((word >> 8) & 0xFFF, (word >> 20) & 3,
                (((word >> 22) & 1) << 8) | (word & 0xFF))
    for bit in range(23):
        assert pins(0) != pins(1 << bit)
    assert pins(0) == pins(1 << 23)
    for offset in (0, 1, 0xFFFF, 0x10000, 0x1FFFF):
        assert pins(CARD[0] + offset) == pins(CARD[0] + offset + 0x800000)
    raw_file_word = (CARD[0] - 0x600000) & 0x7FFFFF
    logical_word = (0x600000 + raw_file_word) & 0xFFFFFF
    assert raw_file_word == 0x740000 and logical_word == 0xD40000
    assert logical_word & 0x7FFFFF == CARD[0]
    assert pins(logical_word) == pins(CARD[0])
    oversized_file = (raw_file_word + 256) * 2
    assert (oversized_file + 511) // 512 == 0x7401
    formats = {"400K": 409600, "800K": 819200, "720K": 737280, "1440K": 1474560}
    for payload in formats.values():
        for header in (0, 84):
            physical_bytes_written = ((payload + header + 511) // 512) * 512 - header
            assert physical_bytes_written <= 2 * 1024 * 1024
    result = {
        "baseline": "07770d622facce6215dc98daa197511286817825",
        "user_confirmed_board_bytes": 128 * 1024 * 1024,
        "controller_addressable_bytes": (1 << 23) * 2,
        "candidate_word_range": [hex(x) for x in CARD],
        "candidate_byte_range": ["0xa80000", "0xabffff"],
        "unconditional_reservation_proved": False,
        "bounded_producer_ranges": {key: [hex(x) for x in pair] for key, pair in ranges.items()},
        "oversized_loader_witness": {"raw_file_bytes": hex(oversized_file),
                                     "file_word": hex(raw_file_word), "file_byte_offset": hex(raw_file_word * 2),
                                     "logical_word": hex(logical_word), "physical_word": hex(logical_word & 0x7FFFFF)},
        "supported_payload_sizes_checked": formats,
        "sources_sha256": PINNED, "source_evidence": evidence,
        "audit_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    producers = [
        ("host RAM and mirrors", "rtl/addrController_top.v", 178, 203, "000000", "4FFFFF", "all physical SIMM configurations"),
        ("host ROM", "rtl/addrController_top.v", 205, 212, "500000", "53FFFF", "includes overlay mirrors"),
        ("host VRAM", "rtl/addrController_top.v", 214, 216, "580000", "5BFFFF", "external backing plus separate BRAM mirror"),
        ("floppy fetch window", "rtl/addrController_top.v", 274, 283, "600000", "7FFFFF", "full 22-bit byte offset bound"),
        ("HPS ioctl ROM", "MacLC.sv", 2235, 2240, "500000", "53FFFF", "address masked to 18 low word bits"),
        ("floppy committer", "MacLC.sv", 2288, 2299, "600000", "7FFFFF", "full 22-bit byte offset bound"),
        ("floppy loader", "rtl/floppy_sd.v", 229, 279, "000000", "7FFFFF", "unbounded mount size can wrap aperture"),
        ("floppy readback block", "rtl/floppy_sd.v", 533, 549, "600000", "7FFFFF", "header source excludes subtraction underflow"),
        ("floppy checksum scan", "rtl/floppy_sd.v", 698, 731, "600000", "7FFFFF", "21-bit scan word offset"),
        ("controller input closure", "MacLC.sv", 2505, 2537, "", "", "CPU, floppy window, download and native inputs only"),
        ("controller address pins", "rtl/sdram.v", 466, 481, "000000", "7FFFFF", "23 word bits; input bit23 ignored"),
        ("controller initialization", "rtl/sdram.v", 363, 406, "", "", "NOP/precharge/refresh/mode; no memory clear writes"),
    ]
    with (HERE / "PRODUCERS.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle)
        writer.writerow(["producer", "path", "first_line", "last_line", "min_physical_word", "max_physical_word", "notes", "source_sha256"])
        for producer, path, first, last, low, high, notes in producers:
            writer.writerow([producer, path, first, last, low, high, notes, PINNED[path]])
    with (HERE / "SOURCES.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "sha256"])
        writer.writerows(PINNED.items())
    print("PASS bounded producer disjointness, 23-bit aperture, supported sizes and oversized-loader alias control")


if __name__ == "__main__":
    main()
