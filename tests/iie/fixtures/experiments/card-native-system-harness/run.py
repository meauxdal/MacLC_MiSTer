#!/usr/bin/env python3
"""Bounded original-upload candidate through native mux and real SDRAM RTL."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-native-system-harness"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    cpu = ROOT / "local/experiments/card-cpu-rtl/source"
    native = ROOT / "fixtures/experiments/native-memory-harness"
    paths = [HERE / "tb_card_native_candidate.sv",
             ROOT / "fixtures/experiments/card-system-harness/card_candidate.sv",
             ROOT / "fixtures/experiments/card-host-rtl/card_host_registers.sv",
             ROOT / "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv",
             ROOT / "fixtures/experiments/memory-harness/card_memory_arbiter.sv",
             native / "card_native_memory_adapter.sv", native / "card_native_port_mux.sv",
             cpu / "cpu_65c02.sv", cpu / "cpu_alu.sv",
             Path("C:/Workspace/Git/MacLC_MiSTer/rtl/sdram.v")]
    for path in paths:
        assert path.is_file(), f"missing expected source: {path}"
    output, warnings = wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s",
                            "tb_card_native_candidate", "-o", linux(WORK / "native-system.vvp"),
                            *map(linux, paths)])
    (WORK / "compile.log").write_text(output + warnings + "\n", encoding="ascii")
    lint_out, lint_err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal",
                              "-DTB_NO_TRISTATE", "--top-module", "tb_card_native_candidate",
                              *map(linux, paths)])
    (WORK / "lint.log").write_text(lint_out + "\n" + lint_err + "\n", encoding="ascii")
    lint_warnings = [line for line in lint_err.splitlines() if line.startswith("%Warning")]
    assert len(lint_warnings) == 2 and all("/rtl/sdram.v:" in line and
                                          "WIDTHEXPAND" in line for line in lint_warnings), lint_warnings
    measured = ROOT / "local/experiments/host-execution/diagnostic-bridge-01/bridge-result.json"
    expected_captures = json.loads(measured.read_text())["captures"]
    assert len(expected_captures) == 39
    inputs = [*paths, Path(__file__).resolve(), measured]
    runs = []
    for fork in (0, 1):
        generated = ROOT / "local/experiments/card-system-harness"
        stimulus, expected = generated / f"stimulus{fork}.txt", generated / f"expected{fork}.hex"
        assert stimulus.is_file() and expected.is_file(), "run card-system-harness first"
        inputs += [stimulus, expected]
        trace = WORK / f"captures{fork}.txt"
        output, errors = wsl(["vvp", linux(WORK / "native-system.vvp"),
                              f"+stimulus={linux(stimulus)}", f"+expected={linux(expected)}",
                              f"+trace={linux(trace)}"])
        assert not errors, errors
        observed = [tuple(int(value, 16) for value in line.split())
                    for line in trace.read_text().splitlines()]
        assert len(observed) == len(expected_captures)
        for row, capture in zip(observed, expected_captures):
            assert row == (capture["status"], int(capture["address"], 16),
                           capture["data"] if capture["write"] else 0)
        (WORK / f"simulation{fork}.log").write_text(output + "\n", encoding="ascii")
        runs.append({"fork": fork, "result": output,
                     "capture_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()})
        print(output)
    result = {"scope": "original-upload card candidate through native adapter, ownership mux and actual SDRAM RTL",
              "boundary": "202F before NOP/IRQ", "runs": runs, "baseline_lint_warnings": lint_warnings,
              "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
