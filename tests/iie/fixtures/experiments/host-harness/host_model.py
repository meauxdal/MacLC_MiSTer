#!/usr/bin/env python3
"""Synthetic ROM-probe and Startup replay; no CPU or physical Gemini model."""

import hashlib
import importlib.util
import json
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Hypothesis:
    # Candidate geometry only: word transfers address both lanes, then increment.
    name: str
    byte_step: int = 1
    word_step: int = 1
    address_mask: int = 0x3FFFF
    high_lane: int = 0


class Trace:
    def __init__(self, sink=None):
        self.counts = Counter()
        self.digest = hashlib.sha256()
        self.sink = sink

    def record(self, write, width, offset, value):
        self.counts[(write, width, offset)] += 1
        self.digest.update(struct.pack(">BBHI", write, width, offset, value))
        if self.sink is not None:
            self.sink.write(json.dumps([write, width, offset, value]) + "\n")

    def summary(self):
        return {
            "transactions": sum(self.counts.values()),
            "sha256": self.digest.hexdigest(),
            "counts": {f"{'W' if w else 'R'}{bits}:+{off:02X}": count
                       for (w, bits, off), count in sorted(self.counts.items())},
        }


class HostStream:
    def __init__(self, hypothesis, opaque_read, trace=None):
        self.hypothesis = hypothesis
        self.opaque_read = opaque_read
        self.trace = trace
        self.memory = bytearray(0x40000)
        self.control = 0
        self.index = 0

    def address(self, lane):
        context = (self.control >> 3) & 1
        return ((context << 17) | (lane << 16) | self.index) & \
            self.hypothesis.address_mask

    def advance(self, step):
        self.index = (self.index + step) & 0xFFFF

    def read(self, offset, width=8):
        if width == 8 and offset in (0x10, 0x11):
            value = self.memory[self.address(offset - 0x10)]
            self.advance(self.hypothesis.byte_step)
        elif width == 16 and offset == 0x10:
            high = self.hypothesis.high_lane
            value = (self.memory[self.address(high)] << 8) | \
                self.memory[self.address(1 - high)]
            self.advance(self.hypothesis.word_step)
        elif width == 16 and offset == 0x1C:
            value = self.index
        elif width == 8 and offset == 0x0D:
            # Readback latch is part of the explicit candidate hypothesis.
            value = self.control
        else:
            # Opaque reads have no modeled memory/index effect. The caller must
            # supply every response; +08 is never silently treated as a reset.
            value = self.opaque_read(offset, width)
        if not 0 <= value < (1 << width):
            raise ValueError("read response exceeds transfer width")
        if self.trace is not None:
            self.trace.record(False, width, offset, value)
        return value

    def write(self, offset, value, width=8):
        if not 0 <= value < (1 << width):
            raise ValueError("write value exceeds transfer width")
        if width == 8 and offset in (0x10, 0x11):
            self.memory[self.address(offset - 0x10)] = value
            self.advance(self.hypothesis.byte_step)
        elif width == 16 and offset == 0x10:
            high = self.hypothesis.high_lane
            self.memory[self.address(high)] = value >> 8
            self.memory[self.address(1 - high)] = value & 0xFF
            self.advance(self.hypothesis.word_step)
        elif width == 8 and offset == 0x0D:
            self.control = value
        elif width == 16 and offset == 0x1C:
            self.index = value
        elif (offset, width) not in ((0x0C, 8), (0x20, 8), (0x20, 16), (0x21, 8)):
            raise ValueError(f"unmodeled write +{offset:02X}/{width}")
        # Control writes above are observed only, with no run/reset/ACK semantics.
        if self.trace is not None:
            self.trace.record(True, width, offset, value)


def rom_probe(bus):
    """Replay the ordinary ROM helper path; no mode/vector or bus-error model."""
    d1 = bus.read(0x1C, 16)
    d2 = 0
    bus.read(0x10, 16)
    d1 = (d1 + 1) & 0xFFFF
    first_equal = d1 == bus.read(0x1C, 16)
    if first_equal:
        for _ in range(3):
            bus.read(0x10, 16)
        d2 = bus.read(0x1C, 16)
    d1 = (d1 + 3) & 0xFFFF
    return {"first_equal": first_equal, "final_equal": d1 == d2,
            "d1": d1, "d2": d2, "word_reads": 4 if first_equal else 1}


def select_bit(bus, enabled):
    control = bus.read(0x0D)
    bus.write(0x0D, control | 8 if enabled else control & 0xF7)


def begin_stream(bus, index):
    bus.read(0x08)
    bus.write(0x1C, index, 16)


def conf_ram(bus):
    for pattern in (0xFFFF, 0):
        begin_stream(bus, 0)
        for _ in range(32768):
            bus.write(0x10, pattern, 16)
            bus.write(0x10, pattern, 16)
        for port in (0x10, 0x11):
            begin_stream(bus, 0)
            for _ in range(65536):
                if bus.read(port) != (pattern & 0xFF):
                    return 1
    return 0


def upload(bus, descriptor, port):
    if len(descriptor) < 6:
        raise ValueError("short upload descriptor")
    _, destination, count = struct.unpack_from("<HHH", descriptor)
    if len(descriptor) != count + 6:
        raise ValueError("resource payload length does not match descriptor")
    begin_stream(bus, destination)
    for value in descriptor[6:]:
        bus.write(port, value)


def conf_uploads(bus, resources):
    try:
        select_bit(bus, False)
        for resource, port, context in (
                (1001, 0x10, 0), (1001, 0x11, 0),
                (1002, 0x10, 1), (1003, 0x10, 1), (1004, 0x10, 1)):
            if context and not bus.control & 8:
                select_bit(bus, True)
            if resource not in resources:
                return -1
            upload(bus, resources[resource], port)
        return 0
    finally:
        select_bit(bus, False)


def conf_prelude(bus, resources):
    """Return at first diagnostic poll, or reproduce an early Conf exit."""
    bus.write(0x0D, 0)
    bus.write(0x20, 0x0802, 16)
    bus.read(0x04, 16)
    bus.write(0x0C, 0)
    for context in (True, False):
        select_bit(bus, context)
        if conf_ram(bus):
            bus.write(0x20, 0x0802, 16)
            return {"error": 1, "diagnostic_pending": False}
    if conf_uploads(bus, resources):
        # Conf $042 branches to $0FE, which replaces the error with zero.
        bus.write(0x20, 0x0802, 16)
        return {"error": 0, "diagnostic_pending": False}
    bus.write(0x21, 0xFC)
    bus.write(0x20, 0x80)
    return {"error": None, "diagnostic_pending": True}


def address_signature(bus):
    """Three byte planes encode every candidate context/lane/index uniquely."""
    for shift in (0, 8, 16):
        for context in (0, 1):
            select_bit(bus, context)
            for lane in (0, 1):
                begin_stream(bus, 0)
                prefix = (context << 17) | (lane << 16)
                for index in range(65536):
                    bus.write(0x10 + lane, ((prefix | index) >> shift) & 0xFF)
        # Read only after all lanes/contexts were populated, so aliases cannot
        # be hidden by writing and immediately checking one selection at a time.
        for context in (0, 1):
            select_bit(bus, context)
            for lane in (0, 1):
                begin_stream(bus, 0)
                prefix = (context << 17) | (lane << 16)
                for index in range(65536):
                    expected = ((prefix | index) >> shift) & 0xFF
                    actual = bus.read(0x10 + lane)
                    if actual != expected:
                        return {"context": context, "lane": lane, "index": index,
                                "shift": shift, "expected": expected, "actual": actual}
    return None


def load_conf_resources(path):
    evidence = json.loads((ROOT / "fixtures/experiments/startup-protocol/evidence.json")
                          .read_text(encoding="utf-8"))
    metadata = json.loads((ROOT / "fixtures/experiments/firmware-memory/metadata.json")
                          .read_text(encoding="utf-8"))
    fork = Path(path).read_bytes()
    digest = hashlib.sha256(fork).hexdigest()
    installed = "5674f658f77e333a91c309f477e2cfbc703c781cc5f914545974fe44d2ecce8c"
    if digest not in (evidence["sha256"], installed):
        raise ValueError("original resource fork hash mismatch")
    if evidence["sha256"] != metadata["resource_fork_sha256"]:
        raise ValueError("baseline evidence fork mismatch")
    parser_path = ROOT / "fixtures/research/software-bringup/inspect_resources.py"
    spec = importlib.util.spec_from_file_location("resource_parser", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    expected = {item["id"]: item for item in evidence["resources"]
                if item["type"] == "Conf" and 1000 <= item["id"] <= 1004}
    result = {}
    found = set()
    for item, raw in parser.resources(fork):
        if item["type"] != "Conf" or item["id"] not in expected:
            continue
        if item["id"] in found:
            raise ValueError("duplicate Conf resource")
        found.add(item["id"])
        if hashlib.sha256(raw).hexdigest() != expected[item["id"]]["sha256"]:
            raise ValueError("Conf resource hash mismatch")
        if item["id"] == 1000:
            continue
        checked = next(row for row in metadata["resources"]
                       if row["type"] == "Conf" and row["id"] == item["id"])
        if hashlib.sha256(raw[6:]).hexdigest() != checked["payload_sha256"]:
            raise ValueError("Conf payload hash mismatch")
        result[item["id"]] = raw
    if len(result) != 4 or len(found) != 5:
        raise ValueError("incomplete Conf inventory")
    return result
