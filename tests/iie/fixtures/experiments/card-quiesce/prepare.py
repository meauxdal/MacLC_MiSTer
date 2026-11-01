#!/usr/bin/env python3
"""Optional controller admission freeze and idle/ready observation hooks."""

import difflib
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-quiesce"
MACLC = Path("C:/Workspace/Git/MacLC_MiSTer")
PIN = "953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04"


def quiesce_support(source):
    nl = "\r\n" if "\r\n" in source else "\n"
    if re.search(r"module sdram\s*#\(", source):
        source, count = re.subn(r"(module sdram\s*#\()", r"\1" + nl +
                               "    parameter ENABLE_QUIESCE = 0,", source, count=1)
    else:
        source, count = re.subn(r"module sdram\s*(?=\()", "module sdram #(" + nl +
                               "    parameter ENABLE_QUIESCE = 0" + nl + ")" + nl, source, count=1)
    assert count == 1
    marker = "\tinput               init,"
    assert source.count(marker) == 1
    source = source.replace(marker, "\tinput               warm_quiesce," + nl +
                            "\toutput              warm_idle," + nl +
                            "\toutput              memory_ready," + nl + marker)
    marker = "wire req_flp   = flp_win && !flp_served;"
    assert source.count(marker) == 1
    source = source.replace(marker, nl.join([
        "wire freeze_new = ENABLE_QUIESCE && warm_quiesce;",
        "assign memory_ready = reset == 0 && !init;",
        "assign warm_idle = freeze_new && memory_ready && !seq_busy && !ref_busy &&",
        "                   !(oe || we || dl_req || eth_req || flp_win || flp_guard);",
        marker,
    ]))
    source, count = re.subn(r"else if \((req_flp \|\| req_dl \|\| (?:req_cpu|grant_cpu) \|\| req_eth)\) begin",
                           r"else if (!freeze_new && (\1)) begin", source, count=1)
    assert count == 1
    line = next(line for line in source.splitlines() if "end else if (ref_due >= REF_OPP" in line)
    source = source.replace(line, line.replace("ref_due >= REF_OPP", "!freeze_new && ref_due >= REF_OPP"))
    return source


def main():
    baseline = (MACLC / "rtl/sdram.v").read_bytes()
    assert hashlib.sha256(baseline).hexdigest() == PIN
    original = baseline.decode("utf-8")
    proposed = quiesce_support(original)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "sdram_quiesce.v").write_bytes(proposed.encode("utf-8"))
    patch = "".join(difflib.unified_diff(original.splitlines(keepends=True), proposed.splitlines(keepends=True),
                                       fromfile="a/rtl/sdram.v", tofile="b/rtl/sdram.v"))
    (HERE / "controller-quiesce.patch").write_bytes(patch.encode("utf-8"))
    (HERE / "patch-results.json").write_text(json.dumps({
        "baseline_sha256": PIN, "patched_sha256": hashlib.sha256(proposed.encode("utf-8")).hexdigest(),
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "default_enabled": False,
    }, indent=2) + "\n", encoding="ascii")
    print("PASS optional source-pinned controller quiesce hooks prepared")


if __name__ == "__main__":
    main()
