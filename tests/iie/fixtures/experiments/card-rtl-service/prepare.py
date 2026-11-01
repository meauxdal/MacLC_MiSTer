#!/usr/bin/env python3
"""Compile the blocking RTL host service using the platform QIP source closure."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-rtl-service"


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
    qip = ROOT / "fixtures/experiments/card-platform/card_platform.qip"
    names = re.findall(r"\[file join \$::quartus\(qip_path\) ([^\]]+)\]", qip.read_text())
    assert len(names) == 12
    closure = [(qip.parent / name).resolve() for name in names]
    service = HERE / "card_rtl_service.sv"
    controller = Path("C:/Workspace/Git/MacLC_MiSTer/rtl/sdram.v")
    paths = [service, *closure, controller]
    for path in paths:
        assert path.is_file(), f"missing expected source: {path}"
    executable = WORK / "service.vvp"
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "card_rtl_service", "-o", linux(executable),
         *map(linux, paths)])
    lint_out, lint_err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal",
                              "-DTB_NO_TRISTATE", "--top-module", "card_rtl_service", *map(linux, paths)])
    warnings = [line for line in lint_err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 2 and all("/rtl/sdram.v:" in line and "WIDTHEXPAND" in line
                                     for line in warnings), warnings
    (WORK / "lint.log").write_text(lint_out + "\n" + lint_err + "\n", encoding="ascii")
    inputs = [*paths, qip, Path(__file__).resolve()]
    result = {"scope": "Blocking PDS/card-platform/real-SDRAM simulation service",
              "executable": executable.relative_to(ROOT).as_posix(), "baseline_lint_warnings": warnings,
              "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "prepare-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(executable)


if __name__ == "__main__":
    main()
