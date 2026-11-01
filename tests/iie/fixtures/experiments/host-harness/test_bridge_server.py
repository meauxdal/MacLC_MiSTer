#!/usr/bin/env python3
"""Bridge handoff, sequencing and persistent transport checks."""

import json
import tempfile
import threading
import time
from pathlib import Path

from bridge_server import Bridge, publish, serve
from diagnostic_model import conf_initial_handshake, conf_reset_sync
from host_model import ROOT, HostStream, Hypothesis, conf_uploads, load_conf_resources


def wait_for(path):
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"missing transport artifact: {path.name}")
        time.sleep(0.002)


def rejects(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("invalid handoff/request accepted")


def main():
    resources = load_conf_resources(ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc")
    stream = HostStream(Hypothesis("handoff test"), lambda offset, width: 0)
    assert conf_uploads(stream, resources) == 0
    assert stream.index == 0x4000 and stream.control == 0
    bridge = Bridge(stream.memory, 0x4000, 0, 0xFC, 0x80)
    rejects(lambda: Bridge(stream.memory[:-1], 0x4000, 0, 0xFC, 0x80))
    rejects(lambda: Bridge(stream.memory, 0x4001, 0, 0xFC, 0x80))
    rejects(lambda: bridge.transact("2 0 8 1 0"))
    assert bridge.sequence == 0
    assert bridge.transact("1 0 8 1 0") == 0x80
    rejects(lambda: bridge.transact("1 0 8 1 0"))
    rejects(lambda: bridge.transact("2 2 8 1 0"))

    class Host:
        def read(self, offset, width=8):
            return bridge.transact(f"{bridge.sequence + 1} 0 {width} {offset} 0")

        def write(self, offset, value, width=8):
            return bridge.transact(f"{bridge.sequence + 1} 1 {width} {offset} {value}")

    assert conf_reset_sync(Host(), max_attempts=1) == 0
    assert conf_initial_handshake(Host()) == 0
    assert bridge.summary()["pc"] == "200E"

    scratch = ROOT / "local/experiments/host-harness"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bridge-test-", dir=scratch) as directory:
        run = Path(directory)
        thread = threading.Thread(target=serve, args=(run,), kwargs={"timeout": 5})
        thread.start()
        try:
            wait_for(run / "server.ready")
            (run / "card-memory.bin").write_bytes(stream.memory)
            publish(run / "handoff.txt", "16384 0 252 128")
            publish(run / "handoff.ready", "ready")
            publish(run / "request-1.txt", "1 0 8 1 0")
            wait_for(run / "response-1.txt")
            assert (run / "response-1.txt").read_text() == "OK 128\n"
            publish(run / "request-2.txt", "1 0 8 1 0")
            wait_for(run / "response-2.txt")
            assert (run / "response-2.txt").read_text().startswith("STOP ValueError:")
        finally:
            publish(run / "server.stop", "stop")
            thread.join(6)
        assert not thread.is_alive()
        result = json.loads((run / "bridge-result.json").read_text())
        assert result["transactions"] == 1 and result["pc"] == "0000"
        assert len((run / "bridge.jsonl").read_text().splitlines()) == 1
    print("PASS: handoff, original CPU handshake, sequence rejection and persistent transport")


if __name__ == "__main__":
    main()
