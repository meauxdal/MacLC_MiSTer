#!/usr/bin/env python3
"""Bounded, dependency-free host-stream checks; original bytes remain local."""

import argparse
import hashlib
import io
import json
import time
from pathlib import Path

from host_model import (ROOT, HostStream, Hypothesis, Trace, address_signature,
                        begin_stream, conf_prelude, conf_ram, conf_uploads,
                        load_conf_resources, select_bit, upload)


def opaque_zero(offset, width):
    if (offset, width) not in ((0x08, 8), (0x04, 16)):
        raise ValueError(f"unscripted read +{offset:02X}/{width}")
    return 0


def make_bus(mask=0x3FFFF, trace=None):
    return HostStream(Hypothesis("two contexts, two lanes, step one; opaque +08",
                                 address_mask=mask), opaque_zero, trace)


def must_reject(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("invalid operation accepted")


def test_width_lane_wrap_and_opaque_reads():
    reads = []

    def opaque(offset, width):
        reads.append((offset, width))
        return len(reads)

    bus = HostStream(Hypothesis("candidate A"), opaque)
    bus.write(0x1C, 0xFFFF, 16)
    bus.write(0x10, 0x1234, 16)
    assert bus.index == 0
    assert bus.memory[0xFFFF] == 0x12 and bus.memory[0x1FFFF] == 0x34
    bus.write(0x10, 0xAB)
    bus.write(0x11, 0xCD)
    assert bus.memory[0] == 0xAB and bus.memory[0x10001] == 0xCD
    assert bus.index == 2
    assert [bus.read(0x08) for _ in range(6)] == [1, 2, 3, 4, 5, 6]
    assert bus.index == 2 and reads == [(0x08, 8)] * 6
    bus.write(0x0D, 0xD7)
    select_bit(bus, True)
    assert bus.control == 0xDF
    select_bit(bus, False)
    assert bus.control == 0xD7
    begin_stream(bus, 0x2345)
    assert bus.index == 0x2345 and reads[-1] == (0x08, 8)
    # Another explicit word-lane hypothesis produces another candidate image.
    reversed_bus = HostStream(Hypothesis("candidate B", high_lane=1), opaque)
    reversed_bus.write(0x10, 0x1234, 16)
    assert reversed_bus.memory[0] == 0x34 and reversed_bus.memory[0x10000] == 0x12


def test_control_writes_are_observations():
    trace = Trace()
    bus = make_bus(trace=trace)
    bus.write(0x1C, 0xFFFF, 16)
    bus.memory[5] = 0x42
    before = bytes(bus.memory)
    for offset, value, width in ((0x20, 0x0802, 16), (0x21, 0xFC, 8),
                                 (0x20, 0x80, 8), (0x0C, 0, 8)):
        bus.write(offset, value, width)
    assert bytes(bus.memory) == before and bus.index == 0xFFFF
    assert trace.counts[(True, 16, 0x20)] == 1
    assert trace.counts[(True, 8, 0x20)] == 1
    must_reject(lambda: bus.read(0x01))
    must_reject(lambda: bus.write(0x22, 0))
    must_reject(lambda: bus.write(0x10, 256))
    must_reject(lambda: upload(bus, b"\x00" * 5, 0x10))
    must_reject(lambda: upload(bus, b"\x00\x00\x00\x00\x01\x00", 0x10))


def test_conf_ram_failure_cleanup(resources):
    class CorruptRead(HostStream):
        def read(self, offset, width=8):
            value = super().read(offset, width)
            return value ^ 1 if offset == 0x10 else value

    sink = io.StringIO()
    bus = CorruptRead(Hypothesis("bad read injection"), opaque_zero, Trace(sink))
    assert conf_prelude(bus, resources) == {"error": 1, "diagnostic_pending": False}
    assert json.loads(sink.getvalue().splitlines()[-1]) == [True, 16, 0x20, 0x0802]
    # The first RAM failure exits before the second context selection.
    assert bus.control == 8


def test_original_uploads(resources, trace_path):
    sink = trace_path.open("w", encoding="ascii") if trace_path else None
    try:
        trace = Trace(sink)
        bus = make_bus(trace=trace)
        assert conf_uploads(bus, resources) == 0
    finally:
        if sink is not None:
            sink.close()
    assert bus.control & 8 == 0
    assert bus.index == 0x4000
    assert trace.counts[(True, 8, 0x10)] == 593
    assert trace.counts[(True, 8, 0x11)] == 575
    assert trace.counts[(False, 8, 0x08)] == 5
    assert trace.counts[(True, 16, 0x1C)] == 5
    assert trace.digest.hexdigest() == \
        "a2faa37673b94d8b51ddf72fd7db8501c738945c25bc559d13d2623b72316947"
    for resource, port, context, destination, count in (
            (1001, 0x10, 0, 0x2000, 575), (1001, 0x11, 0, 0x2000, 575),
            (1002, 0x10, 1, 0x5000, 6), (1003, 0x10, 1, 0x7FFA, 6),
            (1004, 0x10, 1, 0x3FFA, 6)):
        start = (context << 17) | ((port - 0x10) << 16) | destination
        assert bytes(bus.memory[start:start + count]) == resources[resource][6:]
    return trace.summary()


def test_conf_prelude(resources):
    trace = Trace()
    result = conf_prelude(make_bus(trace=trace), resources)
    assert result == {"error": None, "diagnostic_pending": True}
    assert trace.counts[(True, 16, 0x10)] == 262144
    assert trace.counts[(False, 8, 0x10)] == 262144
    assert trace.counts[(False, 8, 0x11)] == 262144
    assert trace.counts[(False, 8, 0x08)] == 17
    assert trace.counts[(True, 16, 0x1C)] == 17
    assert sum(trace.counts.values()) == 787650
    return trace.summary()


def test_missing_resource_false_success(resources):
    outcomes = {}
    for missing in (1001, 1002, 1003, 1004):
        incomplete = {key: value for key, value in resources.items() if key != missing}
        bus = make_bus()
        # Exercise the whole main branch once; upload helper for every missing ID.
        if missing == 1004:
            outcome = conf_prelude(bus, incomplete)
            assert outcome == {"error": 0, "diagnostic_pending": False}
        else:
            assert conf_uploads(bus, incomplete) == -1
        assert not bus.control & 8
        outcomes[str(missing)] = "upload fails; main Conf branch returns zero"
    return outcomes


def test_alias_discrimination():
    outcomes = {}
    for label, mask in (("independent", 0x3FFFF), ("index_bit_0_alias", 0x3FFFE),
                        ("index_bit_15_alias", 0x37FFF), ("lane_alias", 0x2FFFF),
                        ("context_alias", 0x1FFFF)):
        bus = make_bus(mask)
        # Conf uses identical patterns for all addresses, lanes and contexts.
        for context in (True, False):
            select_bit(bus, context)
            assert conf_ram(bus) == 0
        failure = address_signature(bus)
        assert (failure is None) == (label == "independent")
        outcomes[label] = {"conf_ram_error": 0, "signature_first_mismatch": failure}
    # Wrong even/zero byte increments also alias addresses in the stream.
    for step in (0, 2):
        bus = HostStream(Hypothesis(f"byte step {step}", byte_step=step), opaque_zero)
        assert address_signature(bus) is not None
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-fork", type=Path, default=ROOT /
                        "local/experiments/firmware-memory/app221/IIe Startup.rsrc")
    parser.add_argument("--write-upload-trace", action="store_true")
    args = parser.parse_args()
    args.resource_fork = args.resource_fork.resolve()
    started = time.perf_counter()
    resources = load_conf_resources(args.resource_fork)
    local = ROOT / "local/experiments/host-harness"
    if args.write_upload_trace:
        local.mkdir(parents=True, exist_ok=True)
    test_width_lane_wrap_and_opaque_reads()
    test_control_writes_are_observations()
    test_conf_ram_failure_cleanup(resources)
    uploads = test_original_uploads(resources, local / "uploads.jsonl"
                                    if args.write_upload_trace else None)
    prelude = test_conf_prelude(resources)
    missing = test_missing_resource_false_success(resources)
    aliases = test_alias_discrimination()
    print(json.dumps({"scope": "synthetic replay of Conf resources matching Startup 2.2.1",
                      "source_fork": args.resource_fork.relative_to(ROOT).as_posix(),
                      "source_fork_sha256": hashlib.sha256(
                          args.resource_fork.read_bytes()).hexdigest(),
                      "checks_passed": 7, "uploads": uploads, "prelude": prelude,
                      "missing_resources": missing, "alias_cases": aliases,
                      "elapsed_seconds": round(time.perf_counter() - started, 3)},
                     indent=2))


if __name__ == "__main__":
    main()
