#!/usr/bin/env python3
"""Replay original Startup stream operations through candidate host RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-host-rtl"
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
from host_model import HostStream, Hypothesis, Trace, address_signature, conf_prelude, load_conf_resources


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


class Stimulus(Trace):
    def __init__(self, file):
        super().__init__()
        self.file = file

    def record(self, write, width, offset, value):
        super().record(write, width, offset, value)
        self.file.write(f"{int(write):x} {int(width == 16):x} {offset:x} {value:x} 0\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    def wsl(command):
        completed = subprocess.run(["wsl", "--", "bash", "-lc", shlex.join(command)],
                                   capture_output=True, text=True, timeout=120)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        return completed.stdout.strip()
    executable = WORK / "host.vvp"
    wsl(["iverilog", "-g2012", "-s", "tb_host", "-o", linux(executable),
         linux(HERE / "card_host_registers.sv"), linux(HERE / "tb_host.sv")])
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    runs = []
    for name, fork in (("prelude221", forks[0]), ("prelude222d1", forks[1]), ("signatures", None)):
        path = WORK / f"{name}.txt"
        with path.open("w", encoding="ascii", newline="\n") as file:
            trace = Stimulus(file)
            stream = HostStream(Hypothesis("candidate RTL"), lambda offset, width: 0, trace)
            if fork:
                assert conf_prelude(stream, load_conf_resources(fork)) == {"error": None, "diagnostic_pending": True}
                assert trace.summary()["transactions"] == 787650
                assert trace.summary()["sha256"] == "3b0a80338b26804c237e9dd7097f4882bb9d6a83ccdc7ca5d1f3c3cf3223a935"
            else:
                assert address_signature(stream) is None
                for context in (0, 8):
                    stream.write(0x0D, context)
                    for index in (0, 1, 0x7FFF, 0xFFFE, 0xFFFF):
                        stream.write(0x1C, index, 16)
                        stream.write(0x10, 0x12AB, 16)
                        stream.write(0x1C, index, 16)
                        assert stream.read(0x10, 16) == 0x12AB
                        assert stream.read(0x1C, 16) == (index + 1) & 0xFFFF
        expected = WORK / f"{name}.hex"
        expected.write_text("\n".join(f"{b:02x}" for b in stream.memory) + "\n", encoding="ascii")
        log = wsl(["vvp", linux(executable), f"+stimulus={linux(path)}", f"+expected={linux(expected)}"])
        assert log.startswith("PASS "), log
        runs.append({"name": name, "trace": trace.summary(), "result": log,
                     "memory_sha256": hashlib.sha256(stream.memory).hexdigest()})
    inputs = [HERE / "card_host_registers.sv", HERE / "tb_host.sv", Path(__file__),
              ROOT / "fixtures/experiments/host-harness/host_model.py", *forks]
    result = {"scope": "Candidate host register geometry against original prelude and complete address signatures",
              "runs": runs, "inputs_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in inputs}}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
