#!/usr/bin/env python3
"""Snapshot and actual-helper protocol checks for the separate IRQ executable."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-irq-service"
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
sys.path.insert(0, str(ROOT / "fixtures/experiments/card-interrupt-contract"))
from rtl_bridge_server import RTLService
from interrupt_model import conf_interrupt_check


class Bus:
    def __init__(self, service):
        self.service = service
        self.events = []

    def read(self, offset, width=8):
        value = self.service.transact(f"{self.service.sequence + 1} 0 {width} {offset} 0")
        self.events.append([False, width, offset, value])
        return value

    def write(self, offset, value, width=8):
        reply = self.service.transact(f"{self.service.sequence + 1} 1 {width} {offset} {value}")
        assert reply == value
        self.events.append([True, width, offset, value])


def main():
    baseline = ROOT / "local/experiments/host-execution/diagnostic-bridge-01"
    snapshot = baseline / "card-memory.bin"
    raw = snapshot.read_bytes()
    assert len(raw) == 0x40000
    executable = WORK / "service.vvp"
    smoke_dir = WORK / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    smoke = RTLService(smoke_dir, raw, [0x4000, 0, 0xFC, 0x80], executable)
    try:
        bus = Bus(smoke)
        assert bus.read(1) == 0x80 and bus.read(4, 16) == 0xFFFC
    finally:
        smoke.close()
    replay_dir = WORK / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    replay = RTLService(replay_dir, raw, [0x4000, 0, 0xFC, 0x80], executable)
    recorded = baseline / "bridge.jsonl"
    rows = [json.loads(line) for line in recorded.read_text().splitlines()]
    assert len(rows) == 139 and rows[-1] == [True, 8, 0x0C, 0]
    bus = Bus(replay)
    try:
        for write, width, offset, value in rows[:-1]:
            if write:
                bus.write(offset, value, width)
            else:
                assert bus.read(offset, width) == value
        helper_start = len(bus.events)
        assert conf_interrupt_check(bus) == 0
        helper_events = bus.events[helper_start:]
        assert bus.read(0x0C) == 1
        bus.write(0x0C, 0)
        try:
            bus.read(1)
        except RuntimeError as error:
            assert str(error) == "RTL boundary $203A"
        else:
            raise AssertionError("IRQ service did not stop at203A")
    finally:
        replay.close()
    expected_captures_path = baseline / "bridge-result.json"
    expected_captures = json.loads(expected_captures_path.read_text())["captures"]
    expected_captures = [{key: row[key] for key in ("status", "address", "write", "data")}
                         for row in expected_captures]
    assert len(replay.captures) == 42 and replay.captures[:39] == expected_captures
    assert [row["data"] for row in replay.captures[39:]] == [2, 0, 1]
    words = [int(word, 16) for line in (replay_dir / "rtl-final.hex").read_text().splitlines()
             if not line.startswith("//") for word in line.split()]
    final = b"".join(word.to_bytes(2, "little") for word in words)
    expected_path = ROOT / "local/experiments/card-system-harness/expected0.hex"
    expected = bytearray(int(value, 16) for value in expected_path.read_text().split())
    expected[0x1FB], expected[0x1FC], expected[0x200A] = 0x22, 0x35, 1
    assert final == expected, "IRQ dump differs outside expected flags/return-PC/counter"
    inputs = [Path(__file__), HERE / "prepare.py", HERE / "prepare-results.json", snapshot, recorded,
              expected_captures_path, expected_path, ROOT / "fixtures/experiments/host-harness/rtl_bridge_server.py",
              ROOT / "fixtures/experiments/card-interrupt-contract/interrupt_model.py"]
    result = {
        "scope": "isolated IRQ platform service driven by recovered helper; no original Macintosh execution in this test",
        "checks": ["RTLService snapshot initialization and early EOF", "138 recorded original-host prefix transactions",
                   "real Conf200 helper read/ACK/RMW/WAIT order", "42 actual captures and reports2,0,1",
                   "STOP203A", "exact full256KiB final dump"],
        "helper_transactions": helper_events, "stop_pc": replay.pc,
        "final_memory_sha256": hashlib.sha256(final).hexdigest(),
        "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }
    (HERE / "test-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print("PASS IRQ live service:138prefix transactions, actualhelper,42captures,STOP203A,exact256KiB dump")


if __name__ == "__main__":
    main()
