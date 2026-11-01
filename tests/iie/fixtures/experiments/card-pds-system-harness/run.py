#!/usr/bin/env python3
"""Replay original diagnostic contract through PDS strobes and complete card RTL."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-pds-system-harness"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    source = ROOT / "local/experiments/card-cpu-rtl/source"
    paths = [HERE / "card_pds_candidate.sv",
             ROOT / "fixtures/experiments/card-system-harness/card_candidate.sv",
             ROOT / "fixtures/experiments/card-pds-harness/card_pds_adapter.sv",
             ROOT / "fixtures/experiments/card-host-rtl/card_host_registers.sv",
             ROOT / "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv",
             ROOT / "fixtures/experiments/memory-harness/card_memory_arbiter.sv",
             source / "cpu_65c02.sv", source / "cpu_alu.sv"]
    testbench = HERE / "tb_pds_candidate.sv"
    executable = WORK / "system.vvp"
    for path in [*paths, testbench]:
        assert path.is_file(), f"missing expected input: {path}"
    wsl(["iverilog", "-g2012", "-s", "tb_pds_candidate", "-o", linux(executable),
         linux(testbench), *map(linux, paths)])
    lint_out, lint_err = wsl(["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME",
                              "-Wno-PINCONNECTEMPTY", "-Wno-UNUSEDSIGNAL", "--timescale-override", "1ns/1ps",
                              "--top-module", "card_pds_candidate",
                              *map(linux, paths)])
    assert "%Warning" not in lint_err, lint_err
    measured = ROOT / "local/experiments/host-execution/diagnostic-bridge-01/bridge-result.json"
    expected_captures = json.loads(measured.read_text())["captures"]
    assert len(expected_captures) == 39
    baseline = ROOT / "local/experiments/card-system-harness"
    inputs = [*paths, testbench, Path(__file__).resolve(), measured]
    runs = []
    for fork in range(2):
        stimulus = baseline / f"stimulus{fork}.txt"
        image = baseline / f"expected{fork}.hex"
        assert len(stimulus.read_text().splitlines()) == 1325
        inputs += [stimulus, image]
        for delay in (0, 1, 2):
            trace = WORK / f"captures{fork}-{delay}.txt"
            output, errors = wsl(["vvp", linux(executable), f"+stimulus={linux(stimulus)}",
                                  f"+expected={linux(image)}", f"+trace={linux(trace)}", f"+delay={delay}"])
            assert output.startswith("PASS "), output
            observed = [tuple(int(value, 16) for value in line.split())
                        for line in trace.read_text().splitlines()]
            assert len(observed) == 39
            for row, capture in zip(observed, expected_captures):
                assert row == (capture["status"], int(capture["address"], 16),
                               capture["data"] if capture["write"] else 0)
            runs.append({"fork": fork, "delay_scale": delay, "result": output,
                         "capture_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()})
    result = {"scope": "PDS adapter, host registers, actual WDC CPU and committed-memory simulation",
              "boundary": "202F before NOP/IRQ", "lint": "Verilator -Wall clean with DECLFILENAME/PINCONNECTEMPTY/UNUSEDSIGNAL exclusions and uniform timescale",
              "runs": runs, "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                                for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    for run in runs:
        print(run)


if __name__ == "__main__":
    main()
