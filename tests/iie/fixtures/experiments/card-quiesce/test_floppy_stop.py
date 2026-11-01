#!/usr/bin/env python3
"""Bounded source-side floppy stop handshake test with a driven mailbox."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-quiesce/floppy-stop"


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
    sources = [HERE / "card_floppy_stop.sv", HERE / "tb_floppy_stop.sv"]
    binary = WORK / "test.vvp"
    wsl(["iverilog", "-g2012", "-s", "tb_floppy_stop", "-o", linux(binary),
         *map(linux, sources)])
    output, errors = wsl(["vvp", linux(binary)])
    assert not errors and output.startswith("PASS floppy stop: accepted=2 responses=2"), output + errors
    (WORK / "test.log").write_text(output + "\n", encoding="ascii")
    inputs = [Path(__file__), *sources]
    result = {
        "scope": "source-side floppy stop unit test; hand-driven mailbox, no controller or CDC proof",
        "checks": ["stalled offer remains valid with frozen address during stop",
                   "REQ high retains response ACK during stop", "REQ low consumes response once",
                   "response-valid and mailbox-drained tails both delay stop",
                   "new request blocked while stopped", "resume accepts exactly one request",
                   "REQ released before response still drains"],
        "result": output,
        "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in inputs},
    }
    (HERE / "test-floppy-stop-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(output)


if __name__ == "__main__":
    main()
