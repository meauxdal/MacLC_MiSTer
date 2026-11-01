#!/usr/bin/env python3
"""Check live original-host IRQ execution against the recovered Conf helper."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from analyze_rtl_bridge import analyze as baseline_analyze, sha
from host_model import ROOT

sys.path.insert(0, str(ROOT / "fixtures/experiments/card-interrupt-contract"))
from interrupt_model import conf_interrupt_check


def words(path):
    values = [int(token, 16) for line in path.read_text().splitlines()
              for token in line.split("//", 1)[0].split()]
    assert len(values) == 131072 and all(0 <= value <= 65535 for value in values)
    return bytearray(b"".join(value.to_bytes(2, "little") for value in values))


class ObservedBus:
    def __init__(self, events):
        self.events = events
        self.index = 0

    def read(self, offset):
        write, width, actual_offset, value = self.events[self.index]
        assert (write, width, actual_offset) == (False, 8, offset), self.index
        self.index += 1
        return value

    def write(self, offset, value):
        assert self.events[self.index] == [True, 8, offset, value], self.index
        self.index += 1


def analyze(run):
    baseline = ROOT / "local/experiments/host-execution/rtl-bridge-01"
    baseline_analyze(baseline)
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8-sig"))
    base_meta = json.loads((baseline / "run.json").read_text(encoding="utf-8-sig"))
    assert metadata["source_sha256_before"] == metadata["source_sha256_after"] == base_meta["source_sha256_before"]
    assert metadata["irq_bridge"] and metadata["rtl_bridge"] and metadata["mame_exit_code"] == 0
    log = (run / "mame.log").read_text()
    assert "DIAGNOSTIC_STOP STOP RuntimeError: RTL boundary $203A" in log
    assert not any(error in log for error in ("LUA ERROR", "ABSENT_DIALOG", "Unknown command"))
    events = [json.loads(line) for line in (run / "bus.jsonl").read_text().splitlines()]
    prior = [json.loads(line) for line in (baseline / "bus.jsonl").read_text().splitlines()]
    assert events[:787657 + 139] == prior
    for name in ("card-memory.bin", "handoff.txt"):
        assert (run / name).read_bytes() == (baseline / name).read_bytes()
    diagnostic = events[787657:]
    assert diagnostic == [json.loads(line) for line in (run / "bridge.jsonl").read_text().splitlines()]
    # The final prefix ACK is also the first operation of Conf $200.
    bus = ObservedBus(diagnostic[138:])
    assert conf_interrupt_check(bus) == 0
    assert bus.read(0x0D) == 0
    bus.write(0x0D, 4)
    bus.write(0x0C, 0)
    assert bus.index == len(bus.events)
    measured = json.loads((run / "bridge-result.json").read_text())
    old = json.loads((baseline / "bridge-result.json").read_text())
    assert measured["transactions"] == len(diagnostic)
    assert measured["pc"] == "203A" and measured["stop"] == "RuntimeError: RTL boundary $203A"
    assert measured["unsupported_request"] == f"{len(diagnostic) + 1} 0 8 1 0"
    captures = measured["captures"]
    assert captures[:39] == old["captures"] and len(captures) == 42
    assert [c["data"] for c in captures[39:]] in ([2, 0, 1], [2, 2, 1])
    assert all(c["address"] == "C07D" and c["write"] for c in captures[39:])
    actual, expected = words(run / "rtl-final.hex"), words(baseline / "rtl-final.hex")
    assert actual[0x1FD] == 0x20 and actual[0x1FC] in (0x32, 0x35)
    assert actual[0x1FB] & 0x34 == 0x20
    expected[0x1FB:0x1FE] = actual[0x1FB:0x1FE]
    expected[0x200A] = 1
    assert actual == expected, "IRQ full-memory comparison failed"
    prepared = ROOT / "fixtures/experiments/card-irq-service/prepare-results.json"
    manifest = json.loads(prepared.read_text())
    sources = {**manifest["inputs_sha256"], **manifest["generated_sha256"]}
    for name, expected_hash in sources.items():
        source = Path(name) if Path(name).is_absolute() else ROOT / name
        assert sha(source) == expected_hash, name
    paths = [Path(__file__).resolve(), prepared,
             ROOT / "fixtures/experiments/card-interrupt-contract/interrupt_model.py",
             ROOT / "local/experiments/card-irq-service/service.vvp",
             *[Path(__file__).with_name(name) for name in ("execute.ps1", "rtl_bridge_server.py")],
             *[run / name for name in ("run.json", "mame.log", "bus.jsonl", "bridge.jsonl",
                                      "bridge-result.json", "rtl-final.hex", "rtl-service.log")]]
    return {"scope": "original MAME host through candidate IRQ/PDS/WDC/CDC/native-SDRAM RTL",
            "run": metadata, "diagnostic_transactions": len(diagnostic), "captures": len(captures),
            "boundary": "203A before banking test", "Conf_200_result": 0,
            "full_memory_bytes_compared": len(actual),
            "allowed_interrupt_stack_bytes": actual[0x1FB:0x1FE].hex(),
            "final_memory_sha256": hashlib.sha256(actual).hexdigest(),
            "rtl_source_hashes_verified": len(sources),
            "inputs_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(ROOT / "local/experiments/host-execution" / args.run)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print("PASS: original host IRQ helper, 42 captures and full 256 KiB memory")
