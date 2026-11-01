#!/usr/bin/env python3
"""Bounded actual window/controller and extracted consumer-tail checks."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from prepare import HERE, ROOT, WORK, MACLC, PINS, prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args, expected_failure=None):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    if expected_failure:
        assert result.returncode and expected_failure in result.stdout, result.stdout + result.stderr
    elif result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    prepare()
    decoder = MACLC / "rtl/addrDecoder.v"
    assert hashlib.sha256(decoder.read_bytes()).hexdigest() == "4714846b53d8338856f98c2073492561325a130a28966161b6f935ee9cc0249d"
    sources = [HERE / "tb_window_stop.sv", WORK / "addrController_top.v", WORK / "baseline_addrController_top.v",
               WORK / "floppy_read_tail.sv", decoder, WORK / "sdram.v",
               HERE.parent / "card-quiesce/card_warm_reset.sv"]
    binary = WORK / "windows.vvp"
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "tb_window_stop", "-o", linux(binary),
         *map(linux, sources)])
    runs = []
    for phase in (2, 7):
        output, errors = wsl(["vvp", linux(binary), f"+phase={phase}"])
        assert not errors and output.startswith("PASS window-stop"), output + errors
        print(output, flush=True)
        runs.append({"sys_phase_ns": phase, "result": output})
        (WORK / f"phase-{phase}.log").write_text(output + "\n", encoding="ascii")
    out, err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal", "-Wno-PINMISSING",
                    "-DTB_NO_TRISTATE", "--top-module", "tb_window_stop", *map(linux, sources)])
    warnings = [line for line in err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 6 and all("WIDTHEXPAND" in w or "WIDTHTRUNC" in w for w in warnings), err
    (WORK / "lint.log").write_text(out + "\n" + err, encoding="ascii")
    unsafe = WORK / "unsafe_windows.v"
    unsafe.write_text((WORK / "addrController_top.v").read_text().replace(
        "else if (!flp_guard && !dskReadAckInt && !dskReadAckExt)", "else"), encoding="utf-8")
    negative_sources = [unsafe if p.name == "addrController_top.v" else p for p in sources]
    negative_binary = WORK / "unsafe.vvp"
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "tb_window_stop", "-o", linux(negative_binary),
         *map(linux, negative_sources)])
    output, errors = wsl(["vvp", linux(negative_binary)], expected_failure="TRUNCATED_WINDOW")
    print(output, flush=True)
    runs.append({"name": "unsafe-immediate-window-stop-negative", "result": output})
    for relative, pin in PINS.items():
        assert hashlib.sha256((MACLC / relative).read_bytes()).hexdigest() == pin
    inputs = [*sources, unsafe, *(MACLC / name for name in PINS), HERE / "prepare.py", Path(__file__),
              HERE.parent / "card-quiesce/prepare.py"]
    (HERE / "results.json").write_text(json.dumps({
        "scope": "actual window source/decoder/controller; extracted actual floppy consumer pipeline; encoders absent",
        "sys_period_ns": 20, "mem_period_ns": 10, "baseline_sources_unchanged": True,
        "runs": runs, "lint_warnings": warnings,
        "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                          hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
