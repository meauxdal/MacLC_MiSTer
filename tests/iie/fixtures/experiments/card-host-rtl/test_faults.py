#!/usr/bin/env python3
"""Bounded fault and register-strobe checks, independent of long stream replay."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-host-rtl"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(command):
    result = subprocess.run(["wsl", "--", "bash", "-lc", shlex.join(command)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    executable = WORK / "faults.vvp"
    sources = [HERE / "card_host_registers.sv", HERE / "tb_faults.sv"]
    wsl(["iverilog", "-g2012", "-s", "tb_faults", "-o", linux(executable),
         *[linux(path) for path in sources]])
    run = wsl(["vvp", linux(executable)]).stdout.strip()
    assert run.startswith("PASS "), run
    lint = wsl(["verilator", "--lint-only", "-Wall", "--top-module", "card_host_registers",
                linux(sources[0])])
    assert "%Warning" not in lint.stderr, lint.stderr
    result = {"result": run, "lint": "Verilator -Wall clean", "inputs_sha256": {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [*sources, Path(__file__)]}}
    (HERE / "unit-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
