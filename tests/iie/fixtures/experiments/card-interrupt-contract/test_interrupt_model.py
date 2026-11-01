#!/usr/bin/env python3
"""Ordered scripted responses constrain the host helper, not card hardware."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "fixtures/experiments/host-harness"))
from host_model import load_conf_resources
from interrupt_model import conf_interrupt_check


class Bus:
    def __init__(self, reads):
        self.reads = iter(reads)
        self.events = []

    def read(self, offset, width=8):
        expected, value = next(self.reads)
        assert width == 8 and offset == expected
        self.events.append([False, 8, offset, value])
        return value

    def write(self, offset, value, width=8):
        assert width == 8
        self.events.append([True, 8, offset, value])

    def exhausted(self):
        assert next(self.reads, None) is None


def samples(value):
    return [(1, 0), (1, value)]


def timeout():
    return [(1, 0xE0)] + [(1, 0)] * 1001


def tests():
    for status in range(1, 256):
        for command in (0, 0x88, 0xFF):
            bus = Bus(samples(status) + [(0x0C, 2), (0x20, command)] + samples(status)
                      + [(0x20, 0xF1)] + samples(status))
            assert conf_interrupt_check(bus) == 0
            bus.exhausted()
            assert bus.events == [
                [True, 8, 0x0C, 0], [False, 8, 1, 0], [False, 8, 1, status],
                [False, 8, 0x0C, 2], [True, 8, 0x0C, 0],
                [False, 8, 0x20, command], [True, 8, 0x20, command | 0x20],
                [False, 8, 1, 0], [False, 8, 1, status],
                [False, 8, 0x20, 0xF1], [True, 8, 0x20, 0xD1],
                [True, 8, 0x0C, 0], [False, 8, 1, 0], [False, 8, 1, status]]
    for value in range(256):
        if value == 2:
            continue
        bus = Bus(samples(0xE0) + [(0x0C, value)])
        assert conf_interrupt_check(bus) == 11
        bus.exhausted()
        assert [event for event in bus.events if event[0]] == [[True, 8, 0x0C, 0]]
    bus = Bus(timeout())
    assert conf_interrupt_check(bus) == 11
    bus.exhausted()
    assert len(bus.events) == 1003 and bus.events[-1] == [False, 8, 1, 0]
    bus = Bus(samples(1) + [(0x0C, 2), (0x20, 0x88)] + timeout() + [(0x20, 0xAF)])
    assert conf_interrupt_check(bus) == 12
    bus.exhausted()
    assert bus.events[-2:] == [[False, 8, 0x20, 0xAF], [True, 8, 0x20, 0x8F]]
    assert [e for e in bus.events if e[0] and e[2] == 0x0C] == [[True, 8, 0x0C, 0]] * 2
    bus = Bus(samples(0xFF) + [(0x0C, 2), (0x20, 0x88)] + samples(0x17)
              + [(0x20, 0xA8)] + timeout())
    assert conf_interrupt_check(bus) == 12
    bus.exhausted()
    assert [e for e in bus.events if e[0]] == [
        [True, 8, 0x0C, 0], [True, 8, 0x0C, 0], [True, 8, 0x20, 0xA8],
        [True, 8, 0x20, 0x88], [True, 8, 0x0C, 0]]


def check_original(path):
    uploads = load_conf_resources(path)
    parser_path = ROOT / "fixtures/research/software-bringup/inspect_resources.py"
    spec = importlib.util.spec_from_file_location("resource_parser", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    raw = {(meta["type"], meta["id"]): data for meta, data in parser.resources(path.read_bytes())}
    code = raw["Conf", 1000]
    spans = {
        (0x200, 0x244): "146ef15bdcbfc76e99088670eb81b2fa0d5e4f4d7a2a8bc8038cb457a0cffd7a",
        (0x0D0, 0x0D8): "d3d7e8b55e879337e6a839a0dc7114df04dcdf2441c719baa489f4a4030676c0",
        (0x0B4, 0x0C0): "4cccb3c9569cf4ef0aac924f604dcf3e9b09d24e1306b05b4664637554cf457d",
        (0x116, 0x148): "e08b869aa07ff2ab766c6d509b4fee8898d5ad83df5d3337cb59f0d062a599cb",
        (0x33A, 0x364): "e58d46bb40d551325a3a82a8cfc6b53b793b5b2ed72c807f775195b181cc162d",
    }
    for (start, end), expected in spans.items():
        assert hashlib.sha256(code[start:end]).hexdigest() == expected
    assert uploads[1002][6:] == bytes.fromhex("a9028d7dc040")
    assert uploads[1003][6:] == uploads[1004][6:] == bytes.fromhex("00d000200320")
    assert uploads[1001][6 + 0x2F:6 + 0x32] == bytes.fromhex("020058")
    # Existing monitor decode key, validated independently by its payload hash.
    key = b"DoubleX"
    monitor = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw["Monx", 2606]))[6:]
    assert hashlib.sha256(monitor).hexdigest() == "c92e4db8d40298b759d756a23e51e8d99086cb625e4fbe8074c8c9b2a6bad554"
    sites = {0xCB21: 1, 0xFAB4: 2, 0xFAC0: 3, 0xFB63: 4, 0xFBDD: 1, 0xFD78: 6, 0xFFDA: 5}
    for address, operand in sites.items():
        assert monitor[address - 0xC000:address - 0xC000 + 2] == bytes((2, operand))
    return uploads


def main():
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    for path in forks:
        check_original(path)
    tests()
    inputs = [Path(__file__), HERE / "interrupt_model.py", *forks,
              ROOT / "fixtures/experiments/host-harness/host_model.py",
              ROOT / "fixtures/research/software-bringup/inspect_resources.py"]
    result = {"scope": "hand-authored Conf interrupt replay and original resource spans; no hardware interrupt claim",
              "forks_checked": 2, "nonzero_statuses": 255, "wrong_first_data_values": 255,
              "checks": ["exact transaction order", "first WAIT timeout error11 without data read",
                         "first data mismatch error11", "second WAIT timeout error12 after bit5 clear",
                         "third WAIT timeout error12", "all nonzero statuses ignored",
                         "read-modify-write preserves current other command bits", "original spans and monitor escapes"],
              "inputs_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
