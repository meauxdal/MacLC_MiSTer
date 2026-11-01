#!/usr/bin/env python3
"""Bounded WDC RTL experiment using ignored, hash-checked local inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-cpu-rtl"
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
from host_model import HostStream, Hypothesis, conf_uploads, load_conf_resources

ARCHIVE_HASH = "c474744878f2e41865d08eccc8b1f4f7d2b3db6a34ba13d75f3424a839825a9d"
SOURCES = ["rtl/cpu/wdc65c02/cpu_65c02.sv", "rtl/cpu/wdc65c02/cpu_alu.sv",
           "rtl/apple2.v"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def expected_events():
    rows = [(0x80, 0xFFFC, 0, 0, 0), (0xE1, 0xC07D, 0, 0, 0xA5),
            (0xE0, 0xC07D, 1, 0, 0xA5)]
    displays = [(address, bank, status | (8 if bank else 0))
                for bank in (1, 0) for address, status in
                ((0x400, 2), (0x800, 0x22), (0x2000, 4), (0x4000, 0x24))]
    rows += [(s, a, 1, b, 0xA5) for a, b, s in displays]
    rows += [(0x38, 0xC0E9, 1, 0, 0xA5), (0x38, 0xC0E9, 0, 0, 0x17)]
    for a, b, s in displays:
        rows += [(s | 1, a, 1, b, 0x17), (0xE0, 0xC07D, 1, 0, 0x17)]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    source_dir = WORK / "source"
    source_dir.mkdir(exist_ok=True)
    archive = ROOT / "local/Apple-II_MiSTer/Apple-II_MiSTer-master.zip"
    assert sha(archive) == ARCHIVE_HASH, "archive hash changed"
    inputs = {archive.relative_to(ROOT).as_posix(): sha(archive)}
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.comment.decode("ascii") == "c701e64099d633a26cb1de002edfae07fb16a8fa"
        for name in SOURCES:
            target = source_dir / Path(name).name
            target.write_bytes(zipped.read("Apple-II_MiSTer-master/" + name))
            inputs["archive:" + name] = sha(target)
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    for i, fork in enumerate(forks):
        resources = load_conf_resources(fork)
        stream = HostStream(Hypothesis("rtl-candidate"), lambda offset, width: 0)
        assert conf_uploads(stream, resources) == 0
        (WORK / f"image{i}.hex").write_text("\n".join(f"{b:02x}" for b in stream.memory) + "\n", encoding="ascii")
        inputs[fork.relative_to(ROOT).as_posix()] = sha(fork)
    paths = [HERE / "card_cpu_bus.sv", HERE / "tb_diagnostic.sv",
             source_dir / "cpu_65c02.sv", source_dir / "cpu_alu.sv"]
    compile_command = ["iverilog", "-g2012", "-s", "tb_diagnostic", "-o", linux(WORK / "diagnostic.vvp"),
                       *[linux(p) for p in paths]]
    def wsl(command):
        result = subprocess.run(["wsl", "--", "bash", "-lc", shlex.join(command)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout.strip()
    wsl(compile_command)
    lint = wsl(["verilator", "--lint-only", "-Wall", "-Wno-fatal", "--top-module", "card_cpu_bus",
                linux(HERE / "card_cpu_bus.sv"), linux(source_dir / "cpu_65c02.sv"),
                linux(source_dir / "cpu_alu.sv")])
    unit_runs = {}
    for top, image in (("tb_banking", False), ("tb_cancel", True)):
        target = WORK / f"{top}.vvp"
        wsl(["iverilog", "-g2012", "-s", top, "-o", linux(target),
             linux(HERE / f"{top}.sv"), linux(HERE / "card_cpu_bus.sv"),
             linux(source_dir / "cpu_65c02.sv"), linux(source_dir / "cpu_alu.sv")])
        unit_runs[top] = wsl(["vvp", linux(target),
                             *([f"+image={linux(WORK / 'image0.hex')}"] if image else [])])
        assert unit_runs[top].startswith("PASS "), unit_runs[top]
    runs = []
    for fork in range(2):
        for delay in (0, 1, 2):
            trace = WORK / f"trace{fork}-{delay}.txt"
            log = wsl(["vvp", linux(WORK / "diagnostic.vvp"),
                       f"+image={linux(WORK / f'image{fork}.hex')}",
                       f"+trace={linux(trace)}", f"+delay={delay}"])
            assert log.startswith("PASS "), log
            actual = [tuple(int(v, 16) for v in row.split())
                      for row in trace.read_text().splitlines()]
            assert actual == expected_events(), (actual, expected_events())
            runs.append({"fork": fork, "delay_scale": delay, "result": log,
                         "trace_sha256": sha(trace)})
    for path in HERE.glob("*.sv"):
        inputs[path.relative_to(ROOT).as_posix()] = sha(path)
    for name in ("fixtures/experiments/host-harness/host_model.py",
                 "fixtures/research/software-bringup/inspect_resources.py",
                 "fixtures/experiments/startup-protocol/evidence.json",
                 "fixtures/experiments/firmware-memory/metadata.json"):
        inputs[name] = sha(ROOT / name)
    inputs[Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    result = {"scope": "Original diagnostic through $201D with actual local WDC CPU; candidate bus services",
              "license_gate": "CPU/ALU/apple2.v have no explicit reuse grant; extracted only to ignored local storage",
              "tools": {"iverilog": wsl(["iverilog", "-V"]).splitlines()[0],
                        "verilator": wsl(["verilator", "--version"])},
              "lint": "No errors; PINCONNECTEMPTY and DECLFILENAME warnings only",
              "unit_runs": unit_runs, "runs": runs, "inputs_sha256": inputs}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
