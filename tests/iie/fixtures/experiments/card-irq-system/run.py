#!/usr/bin/env python3
"""Actual host/CPU/memory IRQ variant; source-pinned and isolated from baseline."""
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-irq-system"
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
sys.path.insert(0, str(ROOT / "fixtures/experiments/card-interrupt-contract"))
from host_model import HostStream, Hypothesis, Trace, conf_uploads, load_conf_resources
from test_interrupt_model import check_original
from prepare import generate, PINS


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(command):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(command)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return (result.stdout + result.stderr).strip()


def main():
    generated = generate(WORK)
    bench = HERE / "tb_card_irq.sv"
    extra = [ROOT / "fixtures/experiments/memory-harness/card_memory_arbiter.sv",
             ROOT / "local/experiments/card-cpu-rtl/source/cpu_65c02.sv",
             ROOT / "local/experiments/card-cpu-rtl/source/cpu_alu.sv"]
    lint = wsl(["verilator", "--lint-only", "--timing", "-Wall", "-Wno-PINCONNECTEMPTY",
                "-Wno-DECLFILENAME", "-Wno-UNUSEDSIGNAL", "-Wno-BLKSEQ", "--top-module", "tb_card_irq",
                linux(bench), *map(linux, generated + extra)])
    measured = ROOT / "local/experiments/host-execution/diagnostic-bridge-01"
    diagnostic = [json.loads(line) for line in (measured / "bridge.jsonl").read_text().splitlines()]
    captures = json.loads((measured / "bridge-result.json").read_text())["captures"]
    assert len(diagnostic) == 139 and diagnostic[-1] == [True, 8, 12, 0]
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    for fork_number, fork in enumerate(forks):
        check_original(fork)
        trace = io.StringIO()
        stream = HostStream(Hypothesis("IRQ variant upload candidate"), lambda offset, width: 0, Trace(trace))
        assert conf_uploads(stream, load_conf_resources(fork)) == 0
        rows = [json.loads(line) for line in trace.getvalue().splitlines()]
        rows += [[True, 8, 0x21, 0xFC], [True, 8, 0x20, 0x80]]
        text = "".join(f"{int(w)} {int(width == 16)} {off} {value} 0\n" for w, width, off, value in rows)
        # The measured last ACK is the first instruction of Conf $200, replayed by the new helper.
        text += "".join(f"{int(w)} {int(width == 16)} {off} {value} 600\n"
                        for w, width, off, value in diagnostic[:-1])
        (WORK / f"prefix{fork_number}.txt").write_text(text, encoding="ascii")
        expected = bytearray(stream.memory)
        for bank in (0, 1):
            for address in (0x400, 0x800, 0x2000, 0x4000):
                expected[(bank << 16) | address] = 0xA5
        expected[0x1FD], expected[0x1FC] = 0x20, 0x2E
        (WORK / f"expected{fork_number}.hex").write_text("\n".join(f"{b:02x}" for b in expected) + "\n", encoding="ascii")
    modes = [
        ("normal", {}, 0), ("late_sample", {"NMI_DELAY": 100}, 0),
        ("no_nmi", {"SUPPRESS_NMI": 1}, 11), ("no_irq", {"SUPPRESS_IRQ": 1}, 12),
        ("nmi_after_timeout", {"NMI_DELAY": 100000}, 11),
        ("irq_after_timeout", {"IRQ_DELAY": 100000}, 12),
    ]
    runs = []
    for name, settings, error in modes:
        target = WORK / f"{name}.vvp"
        wsl(["iverilog", "-g2012", "-s", "tb_card_irq", "-o", linux(target),
             *[f"-Ptb_card_irq.{key}={value}" for key, value in settings.items()],
             linux(bench), *map(linux, generated + extra)])
        for fork_number in range(2):
            for delay in ((0, 2) if name == "normal" else (1,)):
                trace = WORK / f"capture-{name}-{fork_number}-{delay}.txt"
                events = WORK / f"events-{name}-{fork_number}-{delay}.txt"
                output = wsl(["vvp", linux(target), f"+stimulus={linux(WORK / f'prefix{fork_number}.txt')}",
                              f"+expected={linux(WORK / f'expected{fork_number}.hex')}",
                              f"+trace={linux(trace)}", f"+events={linux(events)}", f"+error={error}", f"+delay={delay}"])
                assert output.startswith("PASS "), output
                observed = [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()]
                for row, capture in zip(observed[:39], captures):
                    assert row == (capture["status"], int(capture["address"], 16), capture["data"] if capture["write"] else 0)
                event_rows = [row.split() for row in events.read_text().splitlines()]
                opcode = [row for row in event_rows if row[0] == "O"]
                assert opcode == [["O", "202f", "02"]]
                stack = [row for row in event_rows if row[0] == "S"]
                if error == 0:
                    assert len(observed) == 42 and observed[39] == (0xE0, 0xC07D, 2)
                    assert observed[41] == (0xE0, 0xC07D, 1)
                    assert [int(row[1], 16) for row in stack] == [0x1FD, 0x1FC, 0x1FB] * 2
                    assert all(row[2] == "20" for row in stack[::3])
                    assert not int(stack[2][2], 16) & 0x10 and not int(stack[5][2], 16) & 0x14
                else:
                    assert len(observed) == (39 if error == 11 else 40)
                runs.append({"mode": name, "fork": fork_number, "backend_delay_scale": delay,
                             "result": output.splitlines()[0], "new_reports": [row[2] for row in observed[39:]],
                             "stack_pushes": stack, "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                             "events_sha256": hashlib.sha256(events.read_bytes()).hexdigest()})
                print(output.splitlines()[0])
    inputs = [Path(__file__), HERE / "prepare.py", bench, *[ROOT / name for name in PINS],
              *extra, *forks, measured / "bridge.jsonl", measured / "bridge-result.json",
              ROOT / "fixtures/experiments/card-interrupt-contract/test_interrupt_model.py",
              ROOT / "fixtures/experiments/card-interrupt-contract/interrupt_model.py",
              ROOT / "fixtures/experiments/host-harness/host_model.py",
              ROOT / "fixtures/experiments/startup-protocol/evidence.json",
              ROOT / "fixtures/experiments/firmware-memory/metadata.json",
              ROOT / "fixtures/research/software-bringup/inspect_resources.py"]
    result = {"scope": "isolated actual host-register/CPU/shared-memory RTL; candidate generic opcode02 NMI, firmware overlay and command bit5 IRQ",
              "success_boundary": "203A before JSR2058", "mask21": "retained without assigned interrupt semantics",
              "runs": runs, "lint": {"result": lint, "excluded_categories":
                                      ["PINCONNECTEMPTY", "DECLFILENAME", "UNUSEDSIGNAL", "BLKSEQ"]},
              "generated_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in generated},
              "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
