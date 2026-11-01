#!/usr/bin/env python3
"""Load original bytes through host RTL, then replay measured host diagnostics."""

import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-system-harness"
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
from host_model import HostStream, Hypothesis, Trace, conf_uploads, load_conf_resources


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    source = ROOT / "local/experiments/card-cpu-rtl/source"
    paths = [HERE / "card_candidate.sv", HERE / "tb_card_candidate.sv",
             ROOT / "fixtures/experiments/card-host-rtl/card_host_registers.sv",
             ROOT / "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv",
             ROOT / "fixtures/experiments/memory-harness/card_memory_arbiter.sv",
             source / "cpu_65c02.sv", source / "cpu_alu.sv"]
    for path in paths:
        assert path.is_file(), f"missing expected source: {path}"
    wsl(["iverilog", "-g2012", "-s", "tb_card_candidate", "-o", linux(WORK / "system.vvp"),
         *map(linux, paths)])
    lint = wsl(["verilator", "--lint-only", "--timing", "-Wall", "-Wno-PINCONNECTEMPTY",
                "-Wno-DECLFILENAME", "-Wno-UNUSEDSIGNAL", "-Wno-BLKSEQ",
                "--top-module", "tb_card_candidate", *map(linux, paths)])
    measured = ROOT / "local/experiments/host-execution/diagnostic-bridge-01"
    diagnostic = [json.loads(line) for line in (measured / "bridge.jsonl").read_text().splitlines()]
    expected_captures = json.loads((measured / "bridge-result.json").read_text())["captures"]
    assert len(diagnostic) == 139 and len(expected_captures) == 39
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    runs = []
    inputs = [*paths, Path(__file__).resolve(), measured / "bridge.jsonl", measured / "bridge-result.json", *forks]
    guards = HERE / "tb_candidate_guards.sv"
    inputs.append(guards)
    for fork_number, fork in enumerate(forks):
        uploads = io.StringIO()
        stream = HostStream(Hypothesis("integrated RTL"), lambda offset, width: 0,
                            Trace(uploads))
        assert conf_uploads(stream, load_conf_resources(fork)) == 0
        rows = [json.loads(row) for row in uploads.getvalue().splitlines()]
        expected = bytearray(stream.memory)
        for bank in (0, 1):
            for address in (0x400, 0x800, 0x2000, 0x4000):
                expected[(bank << 16) | address] = 0xA5
        expected[0x1FD], expected[0x1FC] = 0x20, 0x2E
        image = WORK / f"expected{fork_number}.hex"
        image.write_text("\n".join(f"{byte:02x}" for byte in expected) + "\n", encoding="ascii")
        rows += [[True, 8, 0x21, 0xFC], [True, 8, 0x20, 0x80]]
        stimulus = WORK / f"stimulus{fork_number}.txt"
        stimulus.write_text("".join(f"{int(w)} {int(bits == 16)} {off} {value} 0\n"
                                    for w, bits, off, value in rows) +
                            "".join(f"{int(w)} {int(bits == 16)} {off} {value} 600\n"
                                    for w, bits, off, value in diagnostic), encoding="ascii")
        for delay in (0, 1, 2):
            trace = WORK / f"captures{fork_number}-{delay}.txt"
            output = wsl(["vvp", linux(WORK / "system.vvp"), f"+stimulus={linux(stimulus)}",
                          f"+expected={linux(image)}", f"+trace={linux(trace)}", f"+delay={delay}"])
            observed = [tuple(int(value, 16) for value in line.split())
                        for line in trace.read_text().splitlines()]
            assert len(observed) == len(expected_captures)
            for row, capture in zip(observed, expected_captures):
                assert row[:2] == (capture["status"], int(capture["address"], 16))
                assert row[2] == (capture["data"] if capture["write"] else 0)
            runs.append({"fork": fork_number, "delay_scale": delay, "result": output,
                         "capture_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()})
    result = {"scope": "bounded host-register/WDC CPU/shared-memory RTL candidate, original uploads",
              "boundary": "202F before NOP/IRQ", "runs": runs,
              "lint": {"tool": "Verilator -Wall", "excluded_categories":
                       ["PINCONNECTEMPTY", "DECLFILENAME", "UNUSEDSIGNAL", "BLKSEQ"],
                       "result": lint},
              "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in inputs}}
    checks = wsl(["vvp", linux(WORK / "system.vvp"), f"+stimulus={linux(WORK / 'stimulus0.txt')}",
                  f"+expected={linux(WORK / 'expected0.hex')}", f"+trace={linux(WORK / 'capture-controls.txt')}",
                  "+capture_checks=1"])
    assert checks.startswith("PASS capture controls:"), checks
    result["capture_control_checks"] = checks
    wsl(["iverilog", "-g2012", "-s", "tb_candidate_guards", "-o", linux(WORK / "guards.vvp"),
         linux(guards), *map(linux, [p for p in paths if p.name != "tb_card_candidate.sv"])])
    guard_checks = wsl(["vvp", linux(WORK / "guards.vvp")])
    assert guard_checks.startswith("PASS candidate guards:"), guard_checks
    result["unsupported_access_checks"] = guard_checks
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    for run in runs:
        print(run)


if __name__ == "__main__":
    main()
