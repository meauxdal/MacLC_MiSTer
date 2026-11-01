#!/usr/bin/env python3
"""Optional native byte masks; baseline controller remains untouched."""

import difflib
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MACLC = Path("C:/Workspace/Git/MacLC_MiSTer")
WORK = ROOT / "local/experiments/native-byte-memory"
PIN = "953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04"


def byte_support(source):
    nl = "\r\n" if "\r\n" in source else "\n"
    if re.search(r"module sdram\s*#\(", source):
        source, count = re.subn(r"(module sdram\s*#\()", r"\1" + nl +
                               "    parameter NATIVE_BYTE_ENABLE = 0,", source, count=1)
    else:
        source, count = re.subn(r"module sdram\s*(?=\()", "module sdram #(" + nl +
                               "    parameter NATIVE_BYTE_ENABLE = 0" + nl + ")" + nl, source, count=1)
    assert count == 1
    line = next(line for line in source.splitlines() if line.strip() == "input               eth_we,")
    source = source.replace(line, line + nl + "\tinput [1:0]         eth_ds,     // used only with NATIVE_BYTE_ENABLE")
    source, count = re.subn(r"(ds_q\s*<= req_dl \? 2'b11\s*: (?:req_cpu|grant_cpu) \? ds\s*:) 2'b11;",
                           r"\1 (NATIVE_BYTE_ENABLE ? eth_ds : 2'b11);", source, count=1)
    assert count == 1
    return source


def main():
    original_bytes = (MACLC / "rtl/sdram.v").read_bytes()
    assert hashlib.sha256(original_bytes).hexdigest() == PIN
    original = original_bytes.decode("utf-8")
    modified = byte_support(original)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "sdram_byte.v").write_bytes(modified.encode("utf-8"))
    patch = "".join(difflib.unified_diff(original.splitlines(keepends=True), modified.splitlines(keepends=True),
                                       fromfile="a/rtl/sdram.v", tofile="b/rtl/sdram.v"))
    (HERE / "native-byte-enable.patch").write_bytes(patch.encode("utf-8"))
    (HERE / "patch-results.json").write_text(json.dumps({
        "baseline_sha256": PIN, "default_enabled": False,
        "patched_sha256": hashlib.sha256(modified.encode("utf-8")).hexdigest(),
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="ascii")
    print("PASS source-pinned optional byte-mask patch prepared; baseline unchanged")


if __name__ == "__main__":
    main()
