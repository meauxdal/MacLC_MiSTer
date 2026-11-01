#!/usr/bin/env python3
"""Persistent original-host transport against the assembled RTL endpoint."""

import json
import tempfile

from host_model import ROOT
from rtl_bridge_server import RTLService


def main():
    measured = ROOT / "local/experiments/host-execution/diagnostic-bridge-01"
    events = [json.loads(line) for line in (measured / "bridge.jsonl").read_text().splitlines()]
    baseline = json.loads((measured / "bridge-result.json").read_text())
    scratch = ROOT / "local/experiments/host-harness"
    with tempfile.TemporaryDirectory(prefix="rtl-bridge-test-", dir=scratch) as directory:
        from pathlib import Path
        service = RTLService(Path(directory), (measured / "card-memory.bin").read_bytes(),
                             [0x4000, 0, 0xFC, 0x80])
        try:
            for sequence, (write, width, offset, value) in enumerate(events, 1):
                actual = service.transact(f"{sequence} {int(write)} {width} {offset} {value}")
                assert actual == value, (sequence, actual, value)
            try:
                service.transact(f"{len(events) + 1} 0 8 1 0")
            except RuntimeError as error:
                assert str(error) == "RTL boundary $202F", str(error)
            else:
                raise AssertionError("RTL ran beyond bounded diagnostic")
            expected = [{key: capture[key] for key in ("status", "address", "write", "data")}
                        for capture in baseline["captures"]]
            assert service.captures == expected
            assert (Path(directory) / "rtl-final.hex").is_file()
        finally:
            service.close()
    print("PASS: persistent RTL transport, 139 original host transactions, 39 captures and bounded stop")


if __name__ == "__main__":
    main()
