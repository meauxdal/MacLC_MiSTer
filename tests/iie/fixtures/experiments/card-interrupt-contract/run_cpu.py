#!/usr/bin/env python3
"""Isolated original bytes at logical addresses; pin behavior is a candidate."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-interrupt-contract"
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
from host_model import load_conf_resources


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(command):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(command)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return (result.stdout + result.stderr).strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    sources = [HERE / "tb_interrupt_cpu.sv", ROOT / "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv",
               ROOT / "local/experiments/card-cpu-rtl/source/cpu_65c02.sv",
               ROOT / "local/experiments/card-cpu-rtl/source/cpu_alu.sv"]
    binary = WORK / "interrupt.vvp"
    wsl(["iverilog", "-g2012", "-s", "tb_interrupt_cpu", "-o", linux(binary), *map(linux, sources)])
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    runs = []
    for fork_number, fork in enumerate(forks):
        uploads = load_conf_resources(fork)
        image = bytearray(0x20000)
        for bank in (0, 1):
            for rid in (1001, 1002, 1004):
                raw = uploads[rid]
                address = int.from_bytes(raw[:2], "little")
                image[(bank << 16) + address:(bank << 16) + address + len(raw) - 6] = raw[6:]
        image_path = WORK / f"logical{fork_number}.hex"
        image_path.write_text("\n".join(f"{b:02x}" for b in image) + "\n", encoding="ascii")
        for inject in (0, 1):
            for delay in (0, 1):
                log = wsl(["vvp", linux(binary), f"+image={linux(image_path)}",
                           f"+inject={inject}", f"+delay={delay}"])
                assert log.startswith("PASS "), log
                runs.append({"fork": fork_number, "candidate_interrupts": bool(inject),
                             "delay": delay, "result": log.splitlines()[0]})
    result = {"scope": "isolated original logical CPU image; candidate opcode02 NMI and host IRQ pins, not integrated card mapping",
              "runs": runs, "inputs_sha256": {
                  p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [Path(__file__), *sources, *forks]}}
    (HERE / "cpu-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
