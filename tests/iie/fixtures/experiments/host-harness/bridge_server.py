#!/usr/bin/env python3
"""Bounded file transport between original MAME host execution and py65."""

import argparse
import json
import os
import time
from pathlib import Path

from diagnostic_cpu import DiagnosticCard


class Bridge:
    def __init__(self, memory, index, control, reset_mask, run_control):
        if len(memory) != 0x40000:
            raise ValueError("handoff requires the complete candidate store")
        if (index, control, reset_mask, run_control) != (0x4000, 0, 0xFC, 0x80):
            raise ValueError("unsupported prelude handoff state")
        self.card = DiagnosticCard()
        self.card.stream.memory[:] = memory
        self.card.stream.index = index
        self.card.stream.control = control
        self.card.write(0x21, reset_mask)
        self.card.write(0x20, run_control)
        self.card.events.clear()
        self.sequence = 0

    def transact(self, request):
        sequence, write, width, offset, value = map(int, request.split())
        if sequence != self.sequence + 1:
            raise ValueError("out-of-order bridge request")
        if write not in (0, 1) or width not in (8, 16):
            raise ValueError("unsupported bridge transfer")
        if write:
            self.card.write(offset, value, width)
        else:
            value = self.card.read(offset, width)
        self.sequence = sequence
        return value

    def summary(self):
        processor = self.card.processor
        capture = processor.pending
        return {"transactions": self.sequence, "pc": f"{processor.cpu.pc:04X}",
                "retired_instructions": len(processor.retired),
                "display_writes": len(processor.display_writes),
                "captures": [{"token": c.token, "address": f"{c.address:04X}",
                              "write": c.write, "data": c.data, "pc": c.pc,
                              "status": c.status} for c in processor.captures],
                "pending_token": capture.token if capture else None}


def publish(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="ascii")
    os.replace(temporary, path)


def serve(run, *, timeout=180, max_requests=10000):
    deadline = time.monotonic() + timeout
    bridge = None
    sequence = 1
    result = {"scope": "original Macintosh host with synthetic diagnostic CPU service"}
    publish(run / "server.ready", "ready\n")
    try:
        while time.monotonic() < deadline:
            if (run / "server.stop").exists():
                result["stop"] = "runner stopped"
                break
            if bridge is None:
                if not (run / "handoff.ready").exists():
                    time.sleep(0.002)
                    continue
                state = list(map(int, (run / "handoff.txt").read_text().split()))
                bridge = Bridge((run / "card-memory.bin").read_bytes(), *state)
            request = run / f"request-{sequence}.txt"
            if not request.exists():
                time.sleep(0.002)
                continue
            response = run / f"response-{sequence}.txt"
            if sequence > max_requests:
                raise RuntimeError("bridge request budget exhausted")
            try:
                value = bridge.transact(request.read_text(encoding="ascii"))
            except Exception as error:
                result["stop"] = f"{type(error).__name__}: {error}"
                result["unsupported_request"] = request.read_text().strip()
                publish(response, "STOP " + result["stop"] + "\n")
                break
            with (run / "bridge.jsonl").open("a", encoding="ascii") as trace:
                trace.write(json.dumps(bridge.card.events[-1]) + "\n")
            publish(response, f"OK {value}\n")
            sequence += 1
        else:
            result["stop"] = "bridge wall-clock deadline"
    except Exception as error:
        result["stop"] = f"{type(error).__name__}: {error}"
        publish(run / f"response-{sequence}.txt", "STOP " + result["stop"] + "\n")
    finally:
        if bridge:
            result.update(bridge.summary())
        publish(run / "bridge-result.json", json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    serve(args.run, timeout=args.timeout)
