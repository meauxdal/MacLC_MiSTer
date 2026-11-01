#!/usr/bin/env python3
"""Scripted response checks, not execution of the diagnostic or Gemini."""

import argparse
import hashlib
import importlib.util
import json
import time
from pathlib import Path

from diagnostic_model import (ResetSearchLimit, conf_c0a0_check, conf_c0e8_check,
                              conf_c0e9_check, conf_display_check,
                              conf_display_report_stage,
                              conf_initial_handshake, conf_keyboard_check,
                              conf_reset_sync, conf_vblank_check, conf_wait)
from host_model import ROOT, load_conf_resources


class ScriptedBus:
    def __init__(self, reads):
        self.reads = iter(reads)
        self.events = []

    def read(self, offset, width=8):
        expected_offset, expected_width, value = next(self.reads)
        assert (offset, width) == (expected_offset, expected_width)
        self.events.append([False, width, offset, value])
        return value

    def write(self, offset, value, width=8):
        self.events.append([True, width, offset, value])

    def exhausted(self):
        assert next(self.reads, None) is None


def status_reads(*values):
    return [(1, 8, value) for value in values]


def test_wait():
    for value in range(1, 256):
        bus = ScriptedBus(status_reads(0, value))
        assert conf_wait(bus) == (0, value)
        bus.exhausted()
    # Every possible tested read position, including the final DBRA iteration.
    for delay in range(1001):
        bus = ScriptedBus(status_reads(0xFF, *([0] * delay), 0x80))
        assert conf_wait(bus) == (0, 0x80)
        assert len(bus.events) == delay + 2
        bus.exhausted()
    # A nonzero first read alone cannot prevent timeout.
    bus = ScriptedBus(status_reads(0xE1, *([0] * 1001)))
    assert conf_wait(bus) == (2, 0)
    assert len(bus.events) == 1002
    bus.exhausted()


def test_reset_sync():
    reads = status_reads(0, 0x80) + [(4, 16, 0xFFFD)]
    reads += status_reads(0, 1) + [(4, 16, 0xFFFC)]
    bus = ScriptedBus(reads)
    assert conf_reset_sync(bus, max_attempts=2) == 0
    assert bus.events == [
        [False, 8, 1, 0], [False, 8, 1, 0x80], [False, 16, 4, 0xFFFD],
        [True, 8, 0x0C, 0],
        [False, 8, 1, 0], [False, 8, 1, 1], [False, 16, 4, 0xFFFC],
        [True, 8, 0x20, 0x88], [True, 8, 0x0C, 0], [True, 8, 0x0D, 3]]
    bus.exhausted()
    bus = ScriptedBus(status_reads(*([0] * 1002)))
    assert conf_reset_sync(bus, max_attempts=1) == 2
    assert bus.events[-1] == [True, 16, 0x20, 0x0802]
    assert len(bus.events) == 1003
    bus.exhausted()
    bus = ScriptedBus(status_reads(0, 1) + [(4, 16, 0xFFFD)])
    try:
        conf_reset_sync(bus, max_attempts=1)
    except ResetSearchLimit:
        pass
    else:
        raise AssertionError("unbounded guest search treated as complete")
    assert bus.events[-1] == [True, 8, 0x0C, 0]
    assert len(bus.events) == 4
    bus.exhausted()
    bus = ScriptedBus([])
    try:
        conf_reset_sync(bus, max_attempts=0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid harness bound accepted")
    assert not bus.events


def test_initial_handshake():
    for first, second, error in ((0xE1, 0xE0, 0), (0xE0, None, 7),
                                  (0xE1, 0xE1, 7)):
        reads = status_reads(0, first)
        if second is not None:
            reads += status_reads(0, second)
        bus = ScriptedBus(reads)
        assert conf_initial_handshake(bus) == error
        writes = [event for event in bus.events if event[0]]
        assert writes == ([] if second is None else [[True, 8, 0x19, 0]])
        bus.exhausted()
    for stage in (0, 1):
        reads = status_reads(0, 0xE1) if stage else []
        bus = ScriptedBus(reads + status_reads(*([0] * 1002)))
        assert conf_initial_handshake(bus) == 2
        writes = [event for event in bus.events if event[0]]
        assert writes == ([[True, 8, 0x19, 0]] if stage else [])
        bus.exhausted()


def test_display_and_c0e9():
    for helper, statuses, error in (
            (conf_display_check, (0x0A, 0x2A, 0x0C, 0x2C, 2, 0x22, 4, 0x24), 3),
            (conf_c0e8_check, (0x28, 0x28), 4),
            (conf_c0e9_check, (0x38, 0x38), 5)):
        reads = [sample for status in statuses for sample in status_reads(0, status)]
        bus = ScriptedBus(reads)
        assert helper(bus) == 0
        assert bus.events == [event for status in statuses for event in (
            [True, 8, 0x0C, 0], [False, 8, 1, 0], [False, 8, 1, status])]
        bus.exhausted()
        for index in range(len(statuses)):
            prefix = [sample for status in statuses[:index] for sample in status_reads(0, status)]
            for failure in (status_reads(0, 0xFF), status_reads(*([0] * 1002))):
                bus = ScriptedBus(prefix + failure)
                assert helper(bus) == error
                bus.exhausted()
                assert [e for e in bus.events if e[0]] == [[True, 8, 0x0C, 0]] * (index + 1)


def test_c0a0_keyboard_vblank():
    for index in range(2):
        prefix = status_reads(0, 8) if index else []
        for failure, error in ((status_reads(0, 0xFF), 8),
                               (status_reads(*([0] * 1002)), 2)):
            bus = ScriptedBus(prefix + failure)
            assert conf_c0a0_check(bus) == error
            bus.exhausted()
    bus = ScriptedBus(status_reads(0, 8, 0, 9))
    assert conf_c0a0_check(bus) == 0
    bus.exhausted()

    def keyboard_prefix():
        return [(9, 8, 0x80), (0x0D, 8, 0x12)]

    reads = keyboard_prefix()
    for index, data in enumerate((0xA0, 0xFF, 0x20, 0x7F)):
        reads += status_reads(0, 0x11) + [(0x0C, 8, data)]
        if index == 1:
            reads += [(0x0D, 8, 0x92), (9, 8, 0)]
    bus = ScriptedBus(reads)
    assert conf_keyboard_check(bus) == 0
    bus.exhausted()
    assert [e for e in bus.events if e[0]] == [
        [True, 8, 0x18, 0xA0], [True, 8, 0x0D, 0x92],
        [True, 8, 0x0C, 0], [True, 8, 0x0C, 0],
        [True, 8, 0x0D, 0x12], [True, 8, 0x0C, 0], [True, 8, 0x0C, 0]]
    for stage in range(4):
        prefix = keyboard_prefix()
        for index, data in enumerate((0xA0, 0x80, 0x20, 0)[:stage]):
            prefix += status_reads(0, 1) + [(0x0C, 8, data)]
            if index == 1:
                prefix += [(0x0D, 8, 0x92), (9, 8, 0)]
        for failure, error in ((status_reads(*([0] * 1002)), 2),
                               (status_reads(0, 1) + [(0x0C, 8, (0, 0, 0, 0x80)[stage])], 9)):
            bus = ScriptedBus(prefix + failure)
            assert conf_keyboard_check(bus) == error
            bus.exhausted()
    bus = ScriptedBus([(9, 8, 0)])
    assert conf_keyboard_check(bus) == 9
    assert bus.events == [[True, 8, 0x18, 0xA0], [False, 8, 9, 0]]
    bus = ScriptedBus(keyboard_prefix() + status_reads(0, 1) + [(0x0C, 8, 0xA0)]
                      + status_reads(0, 1) + [(0x0C, 8, 0x80), (0x0D, 8, 0x92), (9, 8, 0x80)])
    assert conf_keyboard_check(bus) == 9
    bus.exhausted()
    assert bus.events[-2:] == [[True, 8, 0x0D, 0x12], [False, 8, 9, 0x80]]

    bus = ScriptedBus([(0x0D, 8, 0x12)] + status_reads(0, 1)
                      + [(0x0C, 8, 0xFF), (0x0D, 8, 0x52)]
                      + status_reads(0, 0xFF) + [(0x0C, 8, 0x7F)])
    assert conf_vblank_check(bus) == 0
    bus.exhausted()
    assert [e for e in bus.events if e[0]] == [
        [True, 8, 0x0D, 0x52], [True, 8, 0x0C, 0],
        [True, 8, 0x0D, 0x12], [True, 8, 0x0C, 0]]
    for stage in range(2):
        prefix = [(0x0D, 8, 0x12)]
        if stage:
            prefix += status_reads(0, 1) + [(0x0C, 8, 0x80), (0x0D, 8, 0x52)]
        for failure, error in ((status_reads(*([0] * 1002)), 2),
                               (status_reads(0, 1) + [(0x0C, 8, 0 if stage == 0 else 0x80)], 10)):
            bus = ScriptedBus(prefix + failure)
            assert conf_vblank_check(bus) == error
            bus.exhausted()


def test_display_reports():
    statuses = (0x0B, 0x2B, 0x0D, 0x2D, 3, 0x23, 5, 0x25)

    def stage(status, address, intermediate=None):
        reads = status_reads(0, status) + [(4, 16, address)]
        if intermediate is not None:
            reads += intermediate
        return reads

    for intermediate in (status_reads(0, 0xE0), status_reads(0, 0xFF),
                         status_reads(*([0] * 1002))):
        reads = [sample for index, status in enumerate(statuses)
                 for sample in stage(status, 0xBEEF, intermediate if index < 7 else None)]
        bus = ScriptedBus(reads)
        assert conf_display_report_stage(bus) == 0
        bus.exhausted()
        expected = [[True, 8, 0x20, 0x98]]
        for index, status in enumerate(statuses):
            expected += [[True, 8, 0x0C, 0], [False, 8, 1, 0],
                         [False, 8, 1, status], [False, 16, 4, 0xBEEF]]
            if index < 7:
                expected += [[False, width, offset, value] for offset, width, value in intermediate]
        expected += [[True, 8, 0x20, 0x88]]
        assert bus.events == expected
    for index in range(8):
        prefix = [sample for status in statuses[:index]
                  for sample in stage(status, 0, status_reads(0, 0xE0))]
        for failure in (status_reads(0, 0xFF), status_reads(*([0] * 1002))):
            bus = ScriptedBus(prefix + failure + [(4, 16, 0xFFFC)])
            assert conf_display_report_stage(bus) == 6
            bus.exhausted()
            assert bus.events[-2:] == [[False, 16, 4, 0xFFFC], [True, 8, 0x20, 0x88]]
            assert [e for e in bus.events if e[0] and e[2] == 0x0C] == [
                [True, 8, 0x0C, 0]] * (index + 1)


def check_original_code(path):
    # Validate both fork maps/hashes through the existing loader first.
    load_conf_resources(path)
    parser_path = ROOT / "fixtures/research/software-bringup/inspect_resources.py"
    spec = importlib.util.spec_from_file_location("resource_parser", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    code, = [raw for item, raw in parser.resources(path.read_bytes())
             if item["type"] == "Conf" and item["id"] == 1000]
    # Guard the exact instruction spans used for this hand-authored replay.
    spans = {
        (0x0AC, 0x0D0): "d7d3b69064bc90ebc201b9724946bd542bae82694fb1f0617565498662d5ec06",
        (0x244, 0x2DC): "2731ce7e46ef76d543bb9bf266b658ce0c72ab08d306c9565ca8a26822ae3af3",
        (0x388, 0x3E6): "ecb334c5bc0d519d524b5a6e42a7b6bc70790884a23c47364c7cb410e07516f9",
        (0x098, 0x0AC): "a41fa29f9c7a0971011063edfa1cce0c1b915bfd6051c242605ddb5313a6e690",
        (0x148, 0x200): "670a3617c00c86129f0b9a853817b0cdddc80d12c337588872ad6c2293e2e215",
        (0x07C, 0x098): "eb983ed0d82b3e44b743c00f72b8864083269736cb207b34f411f32b0ac9ffe6",
        (0x052, 0x07C): "d44b6b59f2b8ee65072f9e92b43a4d886fb1dc66c9aff71c7f2c9625957e3936",
        (0x364, 0x388): "31da3593b2414399b784f7f83d77effcb6f9e47d881c63ccd3e8819a1b079494",
        (0x2DC, 0x300): "fcf99fddcaf202db4f83f2ed8d241c3b08b0ce74b5e1d29f0c7ca7bfd9f6d991",
        (0x3E6, 0x45E): "90161392077bc8dd3fdb1ad272551a68b3d2a8426d4ca76a4658188eef17169e",
        (0x5E4, 0x5FE): "d8eb7049b048463f3309635923f765a97a20728989f720b3cfacfddd81e780ff",
    }
    for (start, end), expected in spans.items():
        assert hashlib.sha256(code[start:end]).hexdigest() == expected, hex(start)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    for path in forks:
        check_original_code(path)
    test_wait()
    test_reset_sync()
    test_initial_handshake()
    test_display_and_c0e9()
    test_display_reports()
    test_c0a0_keyboard_vblank()
    inputs = [Path(__file__).resolve(), Path(__file__).with_name("diagnostic_model.py"),
              Path(__file__).with_name("host_model.py"),
              ROOT / "fixtures/research/software-bringup/inspect_resources.py",
              ROOT / "fixtures/experiments/startup-protocol/evidence.json",
              ROOT / "fixtures/experiments/firmware-memory/metadata.json", *forks]
    result = {"scope": "synthetic Conf polling/reset-sync/handshake/display/report/C0Ex/C0A0/keyboard/vblank replay",
              "checks_passed": 7, "forks_checked": 2,
              "nonzero_status_values": 255, "tested_read_positions": 1001,
              "timeout_status_reads": 1002,
              "inputs_sha256": {p.relative_to(ROOT).as_posix():
                                hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in inputs},
              "elapsed_seconds": round(time.perf_counter() - started, 3)}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="ascii")
    print(encoded, end="")


if __name__ == "__main__":
    main()
