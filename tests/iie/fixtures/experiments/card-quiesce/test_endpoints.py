#!/usr/bin/env python3
"""Bounded actual-WDC and PDS endpoint stop/drain checks."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from endpoints_prepare import ROOT, HERE, WORK, prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def main():
    generated = prepare()
    cpu = ROOT / "local/experiments/card-cpu-rtl/source"
    paths = [HERE / "tb_endpoint_stop.sv", *generated,
             ROOT / "fixtures/experiments/card-host-rtl/card_host_registers.sv",
             ROOT / "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv",
             ROOT / "fixtures/experiments/memory-harness/card_memory_arbiter.sv",
             cpu / "cpu_65c02.sv", cpu / "cpu_alu.sv"]
    for path in paths:
        assert path.is_file(), f"missing expected source: {path}"
    paths.append(HERE / "tb_pds_stop_order.sv")
    runs = []
    for top in ("tb_endpoint_stop", "tb_pds_stop_order"):
        binary = WORK / f"{top}.vvp"
        wsl(["iverilog", "-g2012", "-s", top, "-o", linux(binary), *map(linux, paths)])
        lint = wsl(["verilator", "--lint-only", "--timing", "-Wall", "-Wno-PINCONNECTEMPTY",
                    "-Wno-DECLFILENAME", "-Wno-UNUSEDSIGNAL", "-Wno-BLKSEQ", "--Mdir", linux(WORK / "obj_dir"),
                    "--top-module", top, *map(linux, paths)])
        result = wsl(["vvp", linux(binary)])
        assert result.startswith("PASS actual WDC"), result
        runs.append({"top": top, "result": result, "lint": lint})
        print(result)
    manifest = {"scope": "isolated actual WDC and PDS endpoint stop/drain", "runs": runs,
                "inputs_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in [Path(__file__).resolve(), HERE / "endpoints_prepare.py", *paths]}}
    (HERE / "test-endpoint-results.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
