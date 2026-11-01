#!/usr/bin/env python3
"""Validate original MAME host execution serviced by the live RTL endpoint."""

import argparse
import hashlib
import json
from pathlib import Path

from bridge_server import Bridge
from host_model import ROOT, HostStream, Hypothesis, Trace, conf_prelude, load_conf_resources, rom_probe


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(run):
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8-sig"))
    assert metadata["source_sha256_before"] == metadata["source_sha256_after"] == (
        "5e6b04f58dcf631748baf655d0f5d398d6ecb6729f42226f00dfd378c15f2e60")
    assert metadata["mame_exit_code"] == 0 and metadata["rtl_bridge"]
    log = (run / "mame.log").read_text()
    assert "DIAGNOSTIC_STOP STOP RuntimeError: RTL boundary $202F" in log
    assert not any(error in log for error in ("LUA ERROR", "ABSENT_DIALOG", "Unknown command"))
    for name, value in (("SLOT_RETURN", "d0=00000000"),
                        ("DISCOVERY_RETURN", "d0=FEE00000"), ("CONF_CALL", "base=FEE00000")):
        rows = [line for line in log.splitlines() if line.startswith("DBG " + name + " ")]
        assert len(rows) == 1 and value in rows[0], name
    trace = Trace()
    stream = HostStream(Hypothesis("live RTL handoff"), lambda offset, width: 0, trace)
    assert rom_probe(stream)["final_equal"]
    fork = ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"
    assert conf_prelude(stream, load_conf_resources(fork))["diagnostic_pending"]
    events = [json.loads(line) for line in (run / "bus.jsonl").read_text().splitlines()]
    prelude = Trace()
    for write, width, offset, value in events[:787657]:
        prelude.record(write, width, offset, value)
    assert prelude.summary() == trace.summary()
    handoff = (run / "card-memory.bin").read_bytes()
    assert handoff == stream.memory
    state = list(map(int, (run / "handoff.txt").read_text().split()))
    assert state == [stream.index, stream.control, 0xFC, 0x80]
    model = Bridge(handoff, *state)
    diagnostic = events[787657:]
    assert diagnostic == [json.loads(line) for line in (run / "bridge.jsonl").read_text().splitlines()]
    diagnostic_trace = Trace()
    for sequence, (write, width, offset, value) in enumerate(diagnostic, 1):
        assert model.transact(f"{sequence} {int(write)} {width} {offset} {value}") == value
        diagnostic_trace.record(write, width, offset, value)
    measured = json.loads((run / "bridge-result.json").read_text())
    assert measured["transactions"] == len(diagnostic) == 139
    assert measured["pc"] == "202F" and measured["stop"] == "RuntimeError: RTL boundary $202F"
    assert measured["unsupported_request"] == "140 0 8 1 0"
    try:
        model.transact(measured["unsupported_request"])
    except Exception as error:
        assert type(error).__name__ == "ExecutionLimit"
    else:
        raise AssertionError("software replay no longer stops at RTL boundary")
    expected_captures = [{"status": c.status, "address": f"{c.address:04X}",
                          "write": c.write, "data": c.data} for c in model.card.processor.captures]
    assert measured["captures"] == expected_captures and len(expected_captures) == 39
    words = [int(token, 16) for line in (run / "rtl-final.hex").read_text().splitlines()
             for token in line.split("//", 1)[0].split()]
    assert len(words) == 131072 and all(0 <= word <= 65535 for word in words)
    actual = b"".join(word.to_bytes(2, "little") for word in words)
    expected = bytearray(model.card.stream.memory)
    # WDC reset leaves SP=FD; instruction-level py65 starts at FF.
    expected[0x1FE:0x200] = handoff[0x1FE:0x200]
    expected[0x1FC:0x1FE] = b"\x2E\x20"
    assert actual == expected, "RTL full-memory comparison failed"
    prepared = ROOT / "fixtures/experiments/card-rtl-service/prepare-results.json"
    sources = json.loads(prepared.read_text())["inputs_sha256"]
    for name, expected_hash in sources.items():
        source = Path(name) if Path(name).is_absolute() else ROOT / name
        assert sha(source) == expected_hash, name
    paths = [Path(__file__).resolve(), prepared, fork,
             ROOT / "local/experiments/card-rtl-service/service.vvp",
             *[Path(__file__).with_name(name) for name in
               ("execute.ps1", "execute.lua", "diagnostic_bridge.lua", "rtl_bridge_server.py",
                "bridge_server.py", "diagnostic_cpu.py", "diagnostic_model.py", "host_model.py")],
             *[run / name for name in ("run.json", "mame.log", "bus.jsonl", "bridge.jsonl",
                                        "bridge-result.json", "card-memory.bin", "rtl-input.hex",
                                        "rtl-final.hex", "rtl-service.log", "handoff.txt")]]
    return {"scope": "original LC ROM/installed Startup diagnostics through live PDS/WDC/CDC/native-SDRAM RTL",
            "run": metadata, "prelude": prelude.summary(), "diagnostic": diagnostic_trace.summary(),
            "captures": len(expected_captures), "boundary": "202F before NOP/IRQ",
            "full_memory_bytes_compared": len(actual), "final_memory_sha256": hashlib.sha256(actual).hexdigest(),
            "rtl_source_hashes_verified": len(sources),
            "inputs_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(ROOT / "local/experiments/host-execution" / args.run)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print("PASS: original host, 139 RTL diagnostic transactions, 39 captures and full 256 KiB memory")
