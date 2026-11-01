#!/usr/bin/env python3
"""Bounded original diagnostic replay with actual endpoint warm-stop hooks."""

import hashlib
import json
from pathlib import Path
import re

import endpoints_bench
import endpoints_prepare
import platform_prepare
from prepare import HERE, ROOT, WORK, MACLC, PIN, quiesce_support
from run import linux, wsl


def main():
    generated = endpoints_prepare.prepare()
    platform = platform_prepare.prepare()
    bench = endpoints_bench.prepare()
    qip = ROOT / "fixtures/experiments/card-platform/card_platform.qip"
    closure = [(qip.parent / name).resolve() for name in re.findall(
        r"\[file join \$::quartus\(qip_path\) ([^\]]+)\]", qip.read_text())]
    overrides = {p.name: p for p in [*generated, platform]}
    closure = [overrides.get(p.name, p) for p in closure]
    controller_source = MACLC / "rtl/sdram.v"
    baseline = controller_source.read_bytes()
    assert hashlib.sha256(baseline).hexdigest() == PIN
    controller = platform_prepare.WORK / "sdram.v"
    controller.write_bytes(quiesce_support(baseline.decode("utf-8")).encode("utf-8"))
    sources = [bench, HERE / "card_warm_reset.sv", HERE / "card_floppy_stop.sv", *closure, controller]
    binary = platform_prepare.WORK / "platform.vvp"
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "tb_card_platform", "-o", linux(binary),
         *map(linux, sources)])
    out, err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal", "-DTB_NO_TRISTATE",
                    "--top-module", "tb_card_platform", *map(linux, sources)])
    warnings = [line for line in err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 2 and all("sdram.v:" in line and "WIDTHEXPAND" in line for line in warnings), err
    (platform_prepare.WORK / "platform-lint.log").write_text(out + "\n" + err, encoding="ascii")
    expected_trace = ROOT / "local/experiments/host-execution/diagnostic-bridge-01/bridge-result.json"
    captures = json.loads(expected_trace.read_text())["captures"]
    inputs = [*sources, controller_source, qip, expected_trace,
              HERE / "endpoints_prepare.py", HERE / "platform_prepare.py", HERE / "endpoints_bench.py",
              HERE / "prepare.py", HERE / "run.py", Path(__file__)]
    runs = []
    # Each run injects one reset into a different live endpoint stage.
    for case in range(7):
        fork = case % 2
        half, phase = (7, 1) if fork == 0 else (11, 3)
        fixture = ROOT / "local/experiments/card-system-harness"
        stimulus, expected = fixture / f"stimulus{fork}.txt", fixture / f"expected{fork}.hex"
        assert stimulus.is_file() and expected.is_file(), "missing original diagnostic fixtures"
        inputs += [stimulus, expected]
        trace = platform_prepare.WORK / f"captures-{case}.txt"
        output, errors = wsl(["vvp", linux(binary), f"+stimulus={linux(stimulus)}",
                              f"+expected={linux(expected)}", f"+trace={linux(trace)}",
                              f"+sys_half={half}", f"+sys_phase={phase}", f"+reset_case={case}"])
        assert not errors and f"PASS real-endpoint-warm-reset case={case} resets=2" in output, output + errors
        observed = [tuple(int(v, 16) for v in line.split()) for line in trace.read_text().splitlines()]
        assert observed == [(c["status"], int(c["address"], 16), c["data"] if c["write"] else 0) for c in captures]
        (platform_prepare.WORK / f"platform-{case}.log").write_text(output + "\n", encoding="ascii")
        runs.append({"case": case, "fork": fork, "sys_half_ns": half, "sys_phase_ns": phase,
                     "result": output, "capture_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()})
        print(output, flush=True)
    assert controller_source.read_bytes() == baseline
    (HERE / "endpoint-platform-results.json").write_text(json.dumps({
        "scope": "real WDC/PDS/floppy mailbox endpoints; actual controller; external MacLC producers idle",
        "baseline_controller_unchanged": True, "lint_warnings": warnings, "runs": runs,
        "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                          hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
