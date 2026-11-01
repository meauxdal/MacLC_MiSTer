#!/usr/bin/env python3
"""Bounded interactive pipe, recorded-host replay and stop/dump checks."""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-rtl-service"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


class Service:
    def __init__(self, image, name):
        self.dump = WORK / f"{name}-dump.hex"
        self.lines = []
        self.captures = []
        self.messages = queue.Queue()
        self.process = subprocess.Popen(["wsl", "--exec", "vvp", linux(WORK / "service.vvp"),
                                         f"+image={linux(image)}", f"+dump={linux(self.dump)}"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
        def read():
            for line in self.process.stdout:
                self.messages.put(line.strip())
            self.messages.put(None)
        threading.Thread(target=read, daemon=True).start()
        assert self.receive()[0] == "READY"

    def receive(self):
        while True:
            line = self.messages.get(timeout=10)
            assert line is not None, "service exited before marker"
            self.lines.append(line)
            fields = line.split()
            if fields[0] == "CAP":
                self.captures.append((int(fields[1], 16), int(fields[2], 16),
                                      bool(int(fields[3])), int(fields[4], 16)))
            elif fields[0] in ("READY", "REPLY", "STOP", "ERROR"):
                return fields

    def request(self, sequence, write, width, offset, value):
        self.process.stdin.write(f"{sequence} {int(write)} {width} {offset} {value}\n")
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        self.process.stdin.close()
        try:
            assert self.process.wait(timeout=10) == 0
        finally:
            if self.process.poll() is None:
                self.process.kill()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "local/experiments/host-execution/diagnostic-bridge-01"
    snapshot = baseline / "card-memory.bin"
    raw = snapshot.read_bytes()
    assert len(raw) == 262144
    image = WORK / "input.hex"
    image.write_text("\n".join(f"{int.from_bytes(raw[i:i+2], 'little'):04x}"
                               for i in range(0, len(raw), 2)) + "\n", encoding="ascii")
    smoke = Service(image, "smoke")
    try:
        assert smoke.request(1, False, 8, 1, 0) == ["REPLY", "1", "128"]
        assert smoke.request(2, False, 16, 4, 0) == ["REPLY", "2", "65532"]
    finally:
        smoke.close()
    recorded = baseline / "bridge.jsonl"
    transactions = [json.loads(line) for line in recorded.read_text().splitlines()]
    assert len(transactions) == 139
    replay = Service(image, "recorded")
    try:
        for sequence, (write, width, offset, value) in enumerate(transactions, 1):
            fields = replay.request(sequence, write, width, offset, value if write else 0)
            assert fields == ["REPLY", str(sequence), str(value)], fields
        assert replay.request(140, False, 8, 1, 0) == ["STOP", "140", "202f"]
    finally:
        replay.close()
    expected_result = baseline / "bridge-result.json"
    expected_captures = json.loads(expected_result.read_text())["captures"]
    assert len(replay.captures) == 39
    for row, capture in zip(replay.captures, expected_captures):
        assert row == (capture["status"], int(capture["address"], 16), capture["write"],
                       capture["data"] if capture["write"] else 0)
    words = [int(word, 16) for line in replay.dump.read_text().splitlines()
             if not line.startswith("//") for word in line.split()]
    final = b"".join(word.to_bytes(2, "little") for word in words)
    expected_path = ROOT / "local/experiments/card-system-harness/expected0.hex"
    expected = bytes(int(value, 16) for value in expected_path.read_text().split())
    assert final == expected, "dump differs from independently checked platform final memory"
    invalid = Service(image, "invalid")
    try:
        assert invalid.request(2, False, 8, 1, 0) == ["ERROR", "invalid_request"]
    finally:
        invalid.close()
    unsupported = Service(image, "unsupported")
    try:
        assert unsupported.request(1, False, 8, 0x22, 0) == ["ERROR", "transaction", "1", "34"]
    finally:
        unsupported.close()
    inputs = [Path(__file__).resolve(), HERE / "card_rtl_service.sv", HERE / "prepare.py",
              snapshot, recorded, expected_result, expected_path]
    result = {"checks": ["interactive two-request pipe and early EOF", "139 recorded original-host transactions",
                          "39 actual RTL captures", "STOP and full 256 KiB dump at $202F",
                          "invalid sequence and unsupported register errors"],
              "final_memory_sha256": hashlib.sha256(final).hexdigest(),
              "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in inputs}}
    (HERE / "test-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    (WORK / "recorded.log").write_text("\n".join(replay.lines) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
