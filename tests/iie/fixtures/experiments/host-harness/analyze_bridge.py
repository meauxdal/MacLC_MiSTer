#!/usr/bin/env python3
"""Replay original Macintosh diagnostic transactions through the CPU adapter."""

import argparse
import hashlib
import json
from pathlib import Path

from bridge_server import Bridge
from host_model import ROOT, HostStream, Hypothesis, Trace, conf_prelude, load_conf_resources, rom_probe


def analyze(run):
    log = (run / "mame.log").read_text()
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8-sig"))
    assert metadata["source_sha256_before"] == metadata["source_sha256_after"]
    assert metadata["mame_exit_code"] == 0 and metadata["diagnostic_bridge"]
    assert "DIAGNOSTIC_STOP STOP ExecutionLimit:" in log
    assert not any(error in log for error in ("LUA ERROR", "ABSENT_DIALOG", "Unknown command"))
    for marker in ("DBG SLOT_RETURN ", "DBG DISCOVERY_RETURN ", "DBG CONF_CALL "):
        assert sum(line.startswith(marker) for line in log.splitlines()) == 1, marker
    events = [json.loads(line) for line in (run / "bus.jsonl").read_text().splitlines()]
    prelude = Trace()
    stream = HostStream(Hypothesis("original host bridge"), lambda offset, width: 0, prelude)
    assert rom_probe(stream)["final_equal"]
    assert conf_prelude(stream, load_conf_resources(
        ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"))["diagnostic_pending"]
    assert prelude.summary()["transactions"] == 787657
    observed = Trace()
    for event in events[:787657]:
        write, width, offset, value = event
        observed.record(write, width, offset, value)
    assert observed.summary() == prelude.summary()
    assert (run / "card-memory.bin").read_bytes() == stream.memory
    state = list(map(int, (run / "handoff.txt").read_text().split()))
    assert state == [stream.index, stream.control, 0xFC, 0x80]
    bridge = Bridge(stream.memory, *state)
    diagnostic = events[787657:]
    assert diagnostic == [json.loads(line) for line in (run / "bridge.jsonl").read_text().splitlines()]
    trace = Trace()
    for sequence, (write, width, offset, value) in enumerate(diagnostic, 1):
        assert bridge.transact(f"{sequence} {int(write)} {width} {offset} {value}") == value
        trace.record(write, width, offset, value)
    result = json.loads((run / "bridge-result.json").read_text())
    try:
        bridge.transact(result["unsupported_request"])
    except Exception as error:
        assert result["stop"] == f"{type(error).__name__}: {error}"
    else:
        raise AssertionError("recorded unsupported boundary now executes")
    assert bridge.summary() == {key: result[key] for key in bridge.summary()}
    sources = [Path(__file__).resolve(), *[Path(__file__).with_name(name) for name in
               ("execute.lua", "execute.ps1", "diagnostic_bridge.lua", "bridge_server.py",
                "diagnostic_cpu.py", "diagnostic_model.py", "host_model.py")],
               *[run / name for name in ("bus.jsonl", "bridge.jsonl", "bridge-result.json",
                                         "card-memory.bin", "handoff.txt", "run.json", "mame.log")]]
    return {"scope": "original LC ROM and installed Startup with synthetic diagnostic CPU service",
            "run": metadata, "prelude": prelude.summary(), "diagnostic": trace.summary(),
            "boundary": result["stop"], "cpu": bridge.summary(),
            "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sources}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(ROOT / "local/experiments/host-execution" / args.run)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(f"PASS: original prelude and {result['diagnostic']['transactions']} diagnostic transactions; "
          f"CPU stop ${result['cpu']['pc']}")
