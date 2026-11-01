#!/usr/bin/env python3
"""Bounded checks of the ROM probe and Startup on one register candidate."""

import argparse
import hashlib
import importlib.util
import io
import json
import time
from pathlib import Path

from host_model import (ROOT, HostStream, Hypothesis, Trace, conf_prelude,
                        load_conf_resources, rom_probe)
from test_host_model import opaque_zero


def test_word_reads():
    for high in (0, 1):
        trace = Trace()
        bus = HostStream(Hypothesis("word lanes", high_lane=high), opaque_zero, trace)
        bus.control = 0xD8
        bus.index = 0xFFFF
        bus.memory[bus.address(high)] = 0x12
        bus.memory[bus.address(1 - high)] = 0x34
        before = bytes(bus.memory)
        assert bus.read(0x1C, 16) == bus.read(0x1C, 16) == 0xFFFF
        assert bus.index == 0xFFFF
        assert bus.read(0x10, 16) == 0x1234
        assert bus.index == 0
        assert bytes(bus.memory) == before and bus.control == 0xD8
        assert trace.summary()["transactions"] == 3
        bus.write(0x10, 0xABCD, 16)
        bus.index = 0
        assert bus.read(0x10, 16) == 0xABCD and bus.index == 1


def test_probe_arithmetic():
    path = ROOT / "fixtures/experiments/slot-identity/probe_model.py"
    spec = importlib.util.spec_from_file_location("probe_arithmetic", path)
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    outcomes = {}
    for step in (0, 1, 2):
        bus = HostStream(Hypothesis("word step", word_step=step), opaque_zero)
        accepted = []
        for initial in range(65536):
            bus.index = initial
            actual = rom_probe(bus)
            assert actual == oracle.probe(initial, step), (step, initial, actual)
            assert bus.index == (initial + step * actual["word_reads"]) & 0xFFFF
            if actual["final_equal"]:
                accepted.append(initial)
        assert len(accepted) == (65536 if step == 1 else 1)
        if step != 1:
            assert accepted == [0xFFFC]
        outcomes[str(step)] = {"accepted": len(accepted),
                               "sole_accepted_index": accepted[0]
                               if len(accepted) == 1 else None}
    return outcomes


def test_probe_trace():
    outcomes = {}
    for step, initial in ((1, 0xFFFE), (0, 0), (0, 0xFFFC), (2, 0xFFFC)):
        sink = io.StringIO()
        trace = Trace(sink)
        bus = HostStream(Hypothesis("probe trace", word_step=step), opaque_zero, trace)
        bus.index = initial
        bus.control = 0xA8
        before = bytes(bus.memory)
        outcome = rom_probe(bus)
        full = outcome["first_equal"]
        assert trace.counts == {(False, 16, 0x1C): 3 if full else 2,
                                (False, 16, 0x10): 4 if full else 1}
        expected = [[False, 16, 0x1C, initial], [False, 16, 0x10, 0],
                    [False, 16, 0x1C, (initial + step) & 0xFFFF]]
        if full:
            expected += [[False, 16, 0x10, 0]] * 3
            expected += [[False, 16, 0x1C, (initial + 4 * step) & 0xFFFF]]
        assert [json.loads(line) for line in sink.getvalue().splitlines()] == expected
        assert bytes(bus.memory) == before and bus.control == 0xA8
        outcomes[f"step_{step}_index_{initial:04X}"] = {
            "result": outcome, "final_index": bus.index, "trace": trace.summary()}
    return outcomes


def test_joint_faults(resources):
    outcomes = {}
    for hypothesis, error in ((Hypothesis("word_step_0", word_step=0), 1),
                              (Hypothesis("word_step_2", word_step=2), 1),
                              (Hypothesis("lane_alias", address_mask=0x2FFFF), None),
                              (Hypothesis("reversed_lanes", high_lane=1), None)):
        bus = HostStream(hypothesis, opaque_zero)
        bus.index = 0xFFFC
        probe = rom_probe(bus)
        assert probe["final_equal"]
        startup = conf_prelude(bus, resources)
        assert startup == {"error": error, "diagnostic_pending": error is None}
        outcomes[hypothesis.name] = {"probe": probe, "startup": startup}
    return outcomes


def test_probe_startup(resources):
    bus = HostStream(Hypothesis("shared probe/Startup candidate"), opaque_zero)
    bus.index = 0xFFFE
    bus.control = 0xD8
    boot_trace = Trace()
    bus.trace = boot_trace
    boot = rom_probe(bus)
    assert boot["final_equal"] and bus.index == 2 and bus.control == 0xD8
    startup_trace = Trace()
    bus.trace = startup_trace
    startup = conf_prelude(bus, resources)
    assert startup == {"error": None, "diagnostic_pending": True}
    assert bus.index == 0x4000 and bus.control == 0
    assert startup_trace.summary()["transactions"] == 787650
    assert startup_trace.digest.hexdigest() == \
        "3b0a80338b26804c237e9dd7097f4882bb9d6a83ccdc7ca5d1f3c3cf3223a935"
    before = bytes(bus.memory)
    after_trace = Trace()
    bus.trace = after_trace
    after = rom_probe(bus)
    assert after["final_equal"] and bus.index == 0x4004 and bus.control == 0
    assert bytes(bus.memory) == before
    return {"boot_probe": boot, "boot_trace": boot_trace.summary(),
            "startup": startup, "startup_trace": startup_trace.summary(),
            "post_upload_probe": after, "post_upload_trace": after_trace.summary(),
            "final_index": bus.index,
            "memory_sha256": hashlib.sha256(bus.memory).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-fork", type=Path, default=ROOT /
                        "local/experiments/firmware-memory/app221/IIe Startup.rsrc")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    resources = load_conf_resources(args.resource_fork)
    test_word_reads()
    arithmetic = test_probe_arithmetic()
    traces = test_probe_trace()
    faults = test_joint_faults(resources)
    combined = test_probe_startup(resources)
    inputs = [Path(__file__).resolve(), Path(__file__).with_name("host_model.py"),
              ROOT / "fixtures/experiments/slot-identity/probe_model.py",
              args.resource_fork.resolve()]
    result = {"scope": "synthetic ROM probe and Conf prelude on one register model",
              "checks_passed": 5,
              "inputs_sha256": {path.relative_to(ROOT).as_posix():
                                hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in inputs},
              "initial_indices_per_step": 65536, "probe_steps": arithmetic,
              "probe_traces": traces, "joint_faults": faults, "combined": combined,
              "elapsed_seconds": round(time.perf_counter() - started, 3)}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="ascii")
    print(encoded, end="")


if __name__ == "__main__":
    main()
