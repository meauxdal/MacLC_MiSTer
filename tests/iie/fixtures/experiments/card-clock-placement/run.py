#!/usr/bin/env python3
"""Measure ordinary memory cycles at nominal 32.5/65 MHz clock placement."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-clock-placement"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def summarize(path):
    rows = []
    for line in path.read_text().splitlines():
        address, write, cycles, start, end = line.split()
        rows.append({"address": address, "write": bool(int(write)), "cycles": int(cycles),
                     "nanoseconds": round(float(end) - float(start), 3)})
    result = {}
    for name, filtered in (("read", [r for r in rows if not r["write"]]),
                           ("write", [r for r in rows if r["write"]])):
        result[name] = {"count": len(filtered), "min_ns": min(r["nanoseconds"] for r in filtered),
                        "median_ns": statistics.median(r["nanoseconds"] for r in filtered),
                        "max_ns": max(r["nanoseconds"] for r in filtered),
                        "over_1_02mhz": sum(r["nanoseconds"] > 1e9 / 1020000 for r in filtered),
                        "over_1_9mhz": sum(r["nanoseconds"] > 1e9 / 1900000 for r in filtered)}
    return result


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    qip = ROOT / "fixtures/experiments/card-platform/card_platform.qip"
    names = re.findall(r"\[file join \$::quartus\(qip_path\) ([^\]]+)\]", qip.read_text())
    closure = [(qip.parent / name).resolve() for name in names]
    controller = Path("C:/Workspace/Git/MacLC_MiSTer/rtl/sdram.v")
    generated = ROOT / "local/experiments/card-system-harness"
    stimulus, expected = generated / "stimulus0.txt", generated / "expected0.hex"
    inputs = [qip, *closure, controller, stimulus, expected, Path(__file__).resolve()]
    runs = []
    prototype = [HERE / "card_host_cdc.sv", HERE / "card_frontend_platform.sv"]
    inputs += prototype
    lint_out, lint_err = wsl(["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME",
                              "-Wno-PINCONNECTEMPTY", "-Wno-UNUSEDSIGNAL", "--timescale-override", "1ns/1ps",
                              "--top-module", "card_frontend_platform", *map(linux, [*prototype, *closure])])
    assert "%Warning" not in lint_err, lint_err
    unit = HERE / "tb_card_host_cdc.sv"
    inputs.append(unit)
    unit_executable = WORK / "mailbox.vvp"
    wsl(["iverilog", "-g2012", "-s", "tb_card_host_cdc", "-o", linux(unit_executable),
         linux(unit), linux(prototype[0])])
    unit_result, unit_error = wsl(["vvp", linux(unit_executable)])
    assert not unit_error and unit_result.startswith("PASS "), unit_result + unit_error
    for name, top in (("backend_cdc", "tb_clock_backend_cdc"), ("native", "tb_clock_native"),
                      ("frontend_cdc", "tb_clock_frontend_cdc")):
        tb = HERE / f"{top}.sv"
        inputs.append(tb)
        executable = WORK / f"{name}.vvp"
        paths = [tb, *prototype, *closure, controller]
        wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", top, "-o", linux(executable), *map(linux, paths)])
        trace, latency = WORK / f"{name}-captures.txt", WORK / f"{name}-latency.txt"
        output, errors = wsl(["vvp", linux(executable), f"+stimulus={linux(stimulus)}",
                              f"+expected={linux(expected)}", f"+trace={linux(trace)}", f"+latency={linux(latency)}"])
        assert not errors and output.startswith("PASS "), output + errors
        runs.append({"placement": name, "result": output, "ordinary": summarize(latency),
                     "capture_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                     "latency_trace_sha256": hashlib.sha256(latency.read_bytes()).hexdigest()})
        print(json.dumps(runs[-1], indent=2))
    result = {"scope": "Observed ordinary memory-cycle latency; intentional trap waits excluded",
              "budgets_ns": {"1.02MHz": 1e9 / 1020000, "1.9MHz": 1e9 / 1900000},
              "mailbox_unit": unit_result,
              "lint": "Prototype -Wall passes with explicit filename/unused-output/signal exclusions",
              "runs": runs, "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
