#!/usr/bin/env python3
"""Two-clock PDS/card/floppy platform against unchanged native SDRAM RTL."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-platform"


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
    qip = HERE / "card_platform.qip"
    names = re.findall(r"\[file join \$::quartus\(qip_path\) ([^\]]+)\]", qip.read_text())
    assert len(names) == 12, "unexpected QIP source closure"
    closure = [(HERE / name).resolve() for name in names]
    assert len(set(closure)) == len(closure)
    for path in closure:
        assert path.is_file(), f"missing QIP source: {path}"
    lint_out, lint_err = wsl(["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME",
                              "-Wno-PINCONNECTEMPTY", "-Wno-UNUSEDSIGNAL", "--timescale-override", "1ns/1ps",
                              "--top-module", "card_platform", *map(linux, closure)])
    assert "%Warning" not in lint_err, lint_err
    testbench = HERE / "tb_card_platform.sv"
    controller = Path("C:/Workspace/Git/MacLC_MiSTer/rtl/sdram.v")
    paths = [testbench, *closure, controller]
    executable = WORK / "platform.vvp"
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "tb_card_platform", "-o", linux(executable),
         *map(linux, paths)])
    full_lint_out, full_lint_err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal",
                                       "-DTB_NO_TRISTATE", "--top-module", "tb_card_platform", *map(linux, paths)])
    lint_warnings = [line for line in full_lint_err.splitlines() if line.startswith("%Warning")]
    assert len(lint_warnings) == 2 and all("/rtl/sdram.v:" in line and "WIDTHEXPAND" in line
                                          for line in lint_warnings), lint_warnings
    (WORK / "lint.log").write_text(lint_out + "\n" + lint_err + "\n" + full_lint_out + "\n" + full_lint_err + "\n", encoding="ascii")
    measured = ROOT / "local/experiments/host-execution/diagnostic-bridge-01/bridge-result.json"
    expected_captures = json.loads(measured.read_text())["captures"]
    assert len(expected_captures) == 39
    inputs = [*paths, qip, Path(__file__).resolve(), measured]
    runs = []
    for fork in (0, 1):
        generated = ROOT / "local/experiments/card-system-harness"
        stimulus, expected = generated / f"stimulus{fork}.txt", generated / f"expected{fork}.hex"
        assert stimulus.is_file() and expected.is_file(), "run card-system-harness first"
        inputs += [stimulus, expected]
        for half, phase in ((7, 1), (11, 3)):
            trace = WORK / f"captures{fork}-{half}-{phase}.txt"
            output, errors = wsl(["vvp", linux(executable), f"+stimulus={linux(stimulus)}",
                                  f"+expected={linux(expected)}", f"+trace={linux(trace)}",
                                  f"+sys_half={half}", f"+sys_phase={phase}"])
            assert not errors, errors
            assert output.startswith("PASS "), output
            observed = [tuple(int(value, 16) for value in line.split())
                        for line in trace.read_text().splitlines()]
            assert len(observed) == 39
            for row, capture in zip(observed, expected_captures):
                assert row == (capture["status"], int(capture["address"], 16),
                               capture["data"] if capture["write"] else 0)
            (WORK / f"simulation{fork}-{half}-{phase}.log").write_text(output + "\n", encoding="ascii")
            runs.append({"fork": fork, "sys_period_ns": half * 2, "sys_phase_ns": phase,
                         "memory_period_ns": 10, "result": output,
                         "capture_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()})
            print(output)
    result = {"scope": "Two-clock PDS/card/floppy mailbox platform through actual native SDRAM RTL",
              "boundary": "202F before NOP/IRQ", "runs": runs,
              "qip_sources": [p.relative_to(ROOT).as_posix() for p in closure],
              "lint": "Platform -Wall passes with explicit filename/unused-output/signal exclusions; full testbench has only two unchanged SDRAM width warnings",
              "baseline_lint_warnings": lint_warnings,
              "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
