#!/usr/bin/env python3
"""Isolated loader bounds proposal; never edits the MacLC checkout."""

import difflib
import hashlib
import json
from pathlib import Path

from audit import MACLC, PINNED, pinned_sources

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-memory-allocation"


def main():
    original = pinned_sources()["rtl/floppy_sd.v"]
    source = original
    nl = "\r\n" if "\r\n" in original else "\n"

    def replace(before, after):
        nonlocal source
        assert source.count(before) == 1, before
        source = source.replace(before, after.replace("\n", nl))

    replace("module floppy_loader\r\n" if nl == "\r\n" else "module floppy_loader\n",
            "module floppy_loader #(parameter [63:0] REGION_WORDS = 64'h100000)\n")
    replace("\tlocalparam S_DONE   = 3'd5;", "\tlocalparam S_DONE   = 3'd5;\n\tlocalparam S_REJECT = 3'd6;")
    replace("\treg [23:0] file_word;", "\treg [23:0] base_addr_l;\n\treg [23:0] file_word;")
    marker = "\tlocalparam DC42_HDR_WORDS = 24'd42;   // 84 bytes"
    replace(marker, marker + "\n\n" + "\n".join([
        "\tlocalparam [63:0] REGION_BYTES = REGION_WORDS * 64'd2;",
        "\twire region_valid = REGION_WORDS != 0 && REGION_WORDS <= 64'h800000 &&",
        "\t                    {40'd0, base_addr} + REGION_WORDS <= 64'h800000;",
        "\twire [63:0] file_words = (img_size_l >> 1) + {63'd0, img_size_l[0]};",
    ]))
    replace("\t\t\tstate    <= S_IDLE;", "\t\t\tstate    <= S_IDLE;\n\t\t\tbase_addr_l <= 0;")
    replace("\t\t\t\t\treadonly     <= img_readonly;", "\t\t\t\t\treadonly     <= img_readonly;\n\t\t\t\t\tbase_addr_l  <= base_addr;")
    replace("\t\t\t\t\tif (img_size != 64'd0) begin", "\n".join([
        "\t\t\t\t\tif (img_size != 0 && (!region_valid || img_size > REGION_BYTES + 64'd84)) begin",
        "\t\t\t\t\t\tloading <= 0;",
        "\t\t\t\t\t\tsd_rd <= 0;",
        "\t\t\t\t\t\twr_req <= 0;",
        "\t\t\t\t\t\tstate <= S_REJECT;",
        "\t\t\t\t\tend else if (img_size != 64'd0) begin",
    ]))
    replace("\t\t\t\tstate <= S_DRAIN;      // one cycle for buf_ram's read port", "\n".join([
        "\t\t\t\tif (sd_lba == 0 && (dc42 ? (img_size_l <= 64'd84 ||",
        "\t\t\t\t    img_size_l - 64'd84 > REGION_BYTES) : img_size_l > REGION_BYTES))",
        "\t\t\t\t\tstate <= S_REJECT;",
        "\t\t\t\telse state <= S_DRAIN;",
    ]))
    replace("if (dc42 && (file_word < DC42_HDR_WORDS)) begin",
            "if ((dc42 && file_word < DC42_HDR_WORDS) || {40'd0, file_word} >= file_words) begin")
    replace(nl.join([
        "\t\t\t\t\t\t// last sector's tail. Main serves the partial block and",
        "\t\t\t\t\t\t// the stale remainder drains past the payload end, well",
        "\t\t\t\t\t\t// inside the floppy region. Raw images are 512-multiples,",
    ]), "\n".join([
        "\t\t\t\t\t\t// last sector's tail. S_DRAIN skips padding past EOF.",
        "\t\t\t\t\t\t// Raw images are 512-multiples,",
    ]))
    replace("\t\t\t\t\t\twr_addr <= base_addr +", "\t\t\t\t\t\twr_addr <= base_addr_l +")
    marker = "\t\t\tS_DONE: begin"
    replace(marker, "\n".join([
        "\t\t\tS_REJECT: begin",
        "\t\t\t\tloading <= 0;",
        "\t\t\t\tsd_rd <= 0;",
        "\t\t\t\twr_req <= 0;",
        "\t\t\t\tsize <= 0;",
        "\t\t\t\traw_img <= 0;",
        "\t\t\t\tis_dc42 <= 0;",
        "\t\t\t\tdc42_fmt <= 0;",
        "\t\t\t\tdone <= 1;",
        "\t\t\t\tstate <= S_IDLE;",
        "\t\t\tend",
        "", marker,
    ]))
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "floppy_sd_bounded.v").write_bytes(source.encode("utf-8"))
    patch = "".join(difflib.unified_diff(original.splitlines(keepends=True), source.splitlines(keepends=True),
                                       fromfile="a/rtl/floppy_sd.v", tofile="b/rtl/floppy_sd.v"))
    (HERE / "loader-bounds.patch").write_bytes(patch.encode("utf-8"))
    (HERE / "loader-patch-results.json").write_text(json.dumps({
        "baseline_sha256": PINNED["rtl/floppy_sd.v"],
        "proposal_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "applied_to_host": False,
    }, indent=2) + "\n", encoding="ascii")
    assert hashlib.sha256((MACLC / "rtl/floppy_sd.v").read_bytes()).hexdigest() == PINNED["rtl/floppy_sd.v"]
    print("PASS isolated loader proposal generated; MacLC unchanged")


if __name__ == "__main__":
    main()
