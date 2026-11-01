#!/usr/bin/env python3
"""Bounded asynchronous mailbox checks in WSL."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-memory-cdc"


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
    rtl = HERE / "card_memory_cdc.sv"
    bench = HERE / "tb_card_memory_cdc.sv"
    runs = []
    for width in (17, 24):
        target = WORK / f"cdc{width}.vvp"
        wsl(["iverilog", "-g2012", "-s", "tb_card_memory_cdc", "-o", linux(target),
             f"-Ptb_card_memory_cdc.ADDR_WIDTH={width}", linux(rtl), linux(bench)])
        for src_half, dst_half, phase in ((5, 7, 3), (7, 3, 2), (2, 11, 1), (11, 2, 5)):
            simulation = wsl(["vvp", linux(target), f"+src_half={src_half}",
                              f"+dst_half={dst_half}", f"+phase={phase}"])
            assert simulation.startswith("PASS "), simulation
            runs.append({"width": width, "source_half_period_ns": src_half,
                         "destination_half_period_ns": dst_half, "destination_phase_ns": phase,
                         "result": simulation.splitlines()[0]})
    lint = wsl(["verilator", "--lint-only", "-Wall", "--top-module", "card_memory_cdc", linux(rtl)])
    result = {"scope": "one-outstanding bundled toggle mailbox; coordinated quiescent cold reset",
              "runs": runs, "total_requests": 257 * len(runs), "total_responses": 257 * len(runs),
              "verilator_lint": lint or "PASS; no warnings",
              "iverilog_version": wsl(["iverilog", "-V"]).splitlines()[0],
              "verilator_version": wsl(["verilator", "--version"]),
              "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), rtl, bench)}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
