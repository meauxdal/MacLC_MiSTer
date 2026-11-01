#!/usr/bin/env python3
"""Bounded standalone PDS transaction adaptation checks."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-pds-harness"
MAC = ROOT.parent / "MacLC_MiSTer"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(command):
    result = subprocess.run(["wsl", "--", "bash", "-lc", shlex.join(command)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return (result.stdout + result.stderr).strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    rtl = HERE / "card_pds_adapter.sv"
    bench = HERE / "tb_card_pds_adapter.sv"
    target = WORK / "pds.vvp"
    wsl(["iverilog", "-g2012", "-s", "tb_card_pds_adapter", "-o", linux(target),
         linux(rtl), linux(bench)])
    simulation = wsl(["vvp", linux(target)])
    assert simulation.startswith("PASS "), simulation
    lint = wsl(["verilator", "--lint-only", "-Wall", "--top-module", "card_pds_adapter", linux(rtl)])
    inputs = [Path(__file__), rtl, bench, MAC / "MacLC.sv", MAC / "rtl/addrController_top.v"]
    result = {
        "scope": "standalone synthetic alias PDS-to-host transaction adapter; no MacLC integration",
        "simulation": simulation,
        "verilator_lint": lint or "PASS; no warnings",
        "iverilog_version": wsl(["iverilog", "-V"]).splitlines()[0],
        "verilator_version": wsl(["verilator", "--version"]),
        "inputs_sha256": {p.relative_to(ROOT.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in inputs},
    }
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
