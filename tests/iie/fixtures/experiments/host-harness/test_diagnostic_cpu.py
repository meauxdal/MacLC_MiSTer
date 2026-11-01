#!/usr/bin/env python3
"""Original diagnostic prefix execution; candidate register semantics only."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from diagnostic_cpu import DEPS, DiagnosticCard, ExecutionLimit
from diagnostic_model import (conf_c0a0_check, conf_c0e8_check, conf_c0e9_check, conf_display_check,
                              conf_display_report_stage,
                              conf_initial_handshake, conf_keyboard_check,
                              conf_reset_sync, conf_vblank_check, conf_wait)
from host_model import ROOT, conf_uploads, load_conf_resources


def rejects(action, exception=ValueError):
    try:
        action()
    except exception:
        return
    raise AssertionError("invalid action accepted")


def uploaded(resources, **options):
    card = DiagnosticCard(**options)
    assert conf_uploads(card, resources) == 0
    card.events.clear()
    return card


def start(card):
    card.write(0x21, 0xFC)
    card.write(0x20, 0x80)


def synced(resources, **options):
    card = uploaded(resources, **options)
    start(card)
    assert conf_reset_sync(card, max_attempts=1) == 0
    assert card.processor.cpu.pc == 0x2000
    assert card.processor.accesses == [(False, 0xFFFC, 0), (False, 0xFFFD, 0x20)]
    return card


def test_execution(resources):
    summaries = []
    for lane in (0, 1):
        for vector_base in (0x3FFA, 0x7FFA):
            card = synced(resources, lane=lane, vector_base=vector_base)
            processor = card.processor
            assert conf_initial_handshake(card) == 0
            assert processor.retired == [0x2000, 0x200B]
            assert [(c.address, c.write, c.pc) for c in processor.captures] == [
                (0xFFFC, False, None), (0xC07D, False, 0x200B),
                (0xC07D, True, 0x200E)]
            assert processor.pending.data == 0xA5
            assert processor.cpu.a == 0xA5 and processor.cpu.pc == 0x200E
            assert [a for a in processor.accesses if a[1] == 0xC07D] == [
                (False, 0xC07D, 0xA5)]
            # The helper accepts E0 while its write remains suspended.
            assert card.events[-1] == [False, 8, 1, 0xE0]
            card.write(0x0C, 0)
            assert processor.retired == [0x2000, 0x200B, 0x200E]
            assert processor.cpu.pc == 0x2011 and processor.pending is None
            assert processor.accesses[-1] == (True, 0xC07D, 0xA5)
            display = finish_display(card)
            summaries.append({"lane": lane, "vector_base": f"{vector_base:04X}",
                              "reset_reads": ["FFFC", "FFFD"],
                              "retired_pcs": [f"{pc:04X}" for pc in processor.retired],
                              "stop_pc": "2014", "handshake_error": 0,
                              "display": display})
    return summaries


def finish_display(card):
    processor = card.processor
    lane = processor.lane
    value = processor.cpu.a
    before = bytes(card.stream.memory)
    start_retired = len(processor.retired)
    start_accesses = len(processor.accesses)
    sp = processor.cpu.sp
    assert sp == 0xFF
    for _ in range(12):
        processor.attempt()
    assert processor.cpu.pc == 0x2014 and processor.pending is None
    assert processor.cpu.sp == sp and processor.cpu.a == value
    assert not processor.aux_write
    assert processor.retired[start_retired:] == [0x2011, *range(0x2124, 0x2142, 3), 0x2142]
    assert processor.bank_writes == [(0xC005, value), (0xC004, value)]
    addresses = (0x0400, 0x0800, 0x2000, 0x4000)
    expected = [(addr, (bank << 16) | addr, value)
                for bank in (lane ^ 1, lane) for addr in addresses]
    assert processor.display_writes == expected
    stack = [a for a in processor.accesses[start_accesses:] if 0x100 <= a[1] < 0x200]
    assert stack == [(True, 0x1FF, 0x20), (True, 0x1FE, 0x13),
                     (False, 0x1FE, 0x13), (False, 0x1FF, 0x20)]
    expected_memory = bytearray(before)
    expected_memory[(lane << 16) | 0x1FF] = 0x20
    expected_memory[(lane << 16) | 0x1FE] = 0x13
    for addr, mapped, data in expected:
        expected_memory[mapped] = data
    assert card.stream.memory == expected_memory
    assert not any(addr == 0xC0E9 for write, addr, data in processor.accesses)
    return {"stack_writes": ["01FF:20", "01FE:13"], "return_pc": "2014",
            "display_writes": [{"address": f"{addr:04X}", "mapped": f"{mapped:05X}",
                                "data": data} for addr, mapped, data in expected]}


def test_display_bounds(resources):
    for lane in (0, 1):
        card = synced(resources, lane=lane)
        assert conf_initial_handshake(card) == 0
        card.write(0x0C, 0)
        processor = card.processor
        processor.attempt()  # JSR commits its two stack bytes once.
        assert processor.cpu.pc == 0x2124 and processor.cpu.sp == 0xFD
        processor.attempt()  # RAMWRT selects auxiliary writes, not reads/stack.
        assert processor.aux_write
        assert processor.mapped(0x2000) == (lane << 16) | 0x2000
        assert processor.mapped(0x2000, write=True) == ((lane ^ 1) << 16) | 0x2000
        assert processor.mapped(0x1FE, write=True) == (lane << 16) | 0x1FE
        rejects(lambda: processor.access(0x0300, True, 0x55))
        rejects(lambda: processor.access(0xC006, True, 0x55))
        assert processor.bank_writes == [(0xC005, 0xA5)]
        rejects(lambda: processor.run_until_capture(1), ExecutionLimit)
        assert processor.cpu.pc == 0x212A
        assert processor.display_writes == [(0x0400, ((lane ^ 1) << 16) | 0x0400, 0xA5)]
        for _ in range(9):
            processor.attempt()
        assert processor.cpu.pc == 0x2014 and processor.cpu.sp == 0xFF
        assert len(processor.display_writes) == 8
        assert len(processor.bank_writes) == 2


def test_host_display_and_c0e9(resources):
    summaries = []
    for lane in (0, 1):
        for vector_base in (0x3FFA, 0x7FFA):
            card = synced(resources, lane=lane, vector_base=vector_base)
            assert conf_initial_handshake(card) == 0
            card.write(0x0D, 0)  # Conf $084, before the display helper.
            processor = card.processor
            captures = []
            original_read = card.read

            def observed_read(offset, width=8):
                result = original_read(offset, width)
                capture = processor.pending
                if (offset, width) == (1, 8) and capture and capture not in captures:
                    captures.append(capture)
                    state = processor.cpu.__dict__.copy()
                    accesses = processor.accesses.copy()
                    memory = bytes(card.stream.memory)
                    stores = processor.display_writes.copy()
                    for _ in range(1002):
                        assert original_read(1) == result
                        assert original_read(4, 16) == capture.address
                    assert processor.cpu.__dict__ == state
                    assert processor.accesses == accesses
                    assert bytes(card.stream.memory) == memory
                    assert processor.display_writes == stores
                    assert processor.pending is capture
                    rejects(lambda: card.write(0x19, 0))
                return result

            card.read = observed_read
            assert conf_display_check(card) == 0
            assert [c.address for c in captures] == [0x0400, 0x0800, 0x2000, 0x4000] * 2
            assert [c.status for c in captures] == [0x0A, 0x2A, 0x0C, 0x2C,
                                                    0x02, 0x22, 0x04, 0x24]
            assert [c.aux for c in captures] == [True] * 4 + [False] * 4
            assert len(processor.display_writes) == 7
            assert processor.pending.pc == 0x213F
            last_display = processor.pending
            assert conf_c0e9_check(card) == 0
            assert len(processor.display_writes) == 8
            assert processor.display_writes == [
                (addr, (bank << 16) | addr, 0xA5)
                for bank in (lane ^ 1, lane) for addr in (0x0400, 0x0800, 0x2000, 0x4000)]
            assert [(c.address, c.write, c.pc, c.status) for c in captures[8:]] == [
                (0xC0E9, True, 0x2014, 0x38), (0xC0E9, False, 0x2017, 0x38)]
            rejects(lambda: processor.complete(last_display.token))
            assert processor.cpu.pc == 0x2017 and processor.cpu.sp == 0xFF
            assert processor.pending.address == 0xC0E9 and not processor.pending.write
            assert [(w, a, d) for w, a, d in processor.accesses if a == 0xC0E9] == [
                (True, 0xC0E9, 0xA5)]
            card.read_reply = 0x17
            card.write(0x0C, 0)
            assert processor.cpu.pc == 0x201A and processor.cpu.a == 0x17
            assert processor.accesses[-1] == (False, 0xC0E9, 0x17)
            summaries.append({"lane": lane, "vector_base": f"{vector_base:04X}",
                              "display_statuses": [f"{c.status:02X}" for c in captures[:8]],
                              "c0e9_statuses": [f"{c.status:02X}" for c in captures[8:]],
                              "stop_pc": "201A", "display_error": 0, "c0e9_error": 0})
    return summaries


def display_report_ready(resources, **options):
    card = synced(resources, **options)
    assert conf_initial_handshake(card) == 0
    card.write(0x0D, 0)
    assert conf_display_check(card) == 0
    assert conf_c0e9_check(card) == 0
    return card


def test_host_display_reports(resources):
    summaries = []
    for lane in (0, 1):
        for vector_base in (0x3FFA, 0x7FFA):
            card = display_report_ready(resources, lane=lane, vector_base=vector_base,
                                        read_reply=0x17)
            processor = card.processor
            before = bytearray(card.stream.memory)
            start = len(processor.captures)
            card.events.clear()
            assert conf_display_report_stage(card) == 0
            captures = processor.captures[start:]
            assert len(captures) == 15
            displays = captures[::2]
            reports = captures[1::2]
            addresses = (0x0400, 0x0800, 0x2000, 0x4000) * 2
            assert [c.address for c in displays] == list(addresses)
            assert [c.status for c in displays] == [0x0B, 0x2B, 0x0D, 0x2D, 3, 0x23, 5, 0x25]
            assert [c.pc for c in displays] == [0x2078, 0x207E, 0x2084, 0x208A,
                                               0x2093, 0x2099, 0x209F, 0x20A5]
            assert all(c.address_release and c.write and c.data == 0x17 for c in displays)
            assert all(c.address == 0xC07D and c.status == 0xE0 and c.data == 0x17
                       for c in reports)
            assert [c.pc for c in reports] == [c.pc + 3 for c in displays[:-1]]
            assert processor.cpu.pc == 0x20A8 and processor.pending is None
            assert processor.cpu.sp == 0xFD and not processor.report_mode
            assert len(processor.display_writes) == 16
            before[(lane << 16) | 0x1FE] = 0x1C
            for bank in (lane ^ 1, lane):
                for address in addresses[:4]:
                    before[(bank << 16) | address] = 0x17
            assert card.stream.memory == before
            expected_events = [[True, 8, 0x20, 0x98]]
            for index, capture in enumerate(displays):
                expected_events += [[True, 8, 0x0C, 0],
                                    [False, 8, 1, capture.status],
                                    [False, 8, 1, capture.status],
                                    [False, 16, 4, capture.address]]
                if index < 7:
                    expected_events += [[False, 8, 1, 0xE0]] * 2
            expected_events += [[True, 8, 0x20, 0x88]]
            assert card.events == expected_events
            # The last report is first observed after the caller restores $88.
            assert conf_wait(card) == (0, 0xE0)
            last = processor.pending
            assert last.pc == 0x20A8 and last.data == 0x17
            state = processor.cpu.__dict__.copy()
            memory = bytes(card.stream.memory)
            accesses = processor.accesses.copy()
            for _ in range(1002):
                assert card.read(1) == 0xE0
                assert card.read(4, 16) == 0xC07D
            assert processor.cpu.__dict__ == state and processor.accesses == accesses
            assert bytes(card.stream.memory) == memory
            rejects(lambda: card.write(0x19, 0))
            card.write(0x0C, 0)
            rejects(lambda: processor.complete(last.token))
            processor.attempt()  # RTS; preserve the intermediate return boundary.
            assert processor.cpu.pc == 0x201D and processor.cpu.sp == 0xFF
            state = processor.cpu.__dict__.copy()
            accesses = processor.accesses.copy()
            for _ in range(2):
                assert processor.cpu.pc == 0x201D
            assert processor.cpu.__dict__ == state and processor.accesses == accesses
            assert 0x20AB in processor.retired and 0x201D not in processor.retired
            assert sum(w and a == 0xC07D for w, a, d in processor.accesses) == 9
            summaries.append({"lane": lane, "vector_base": f"{vector_base:04X}",
                              "display_statuses": [f"{c.status:02X}" for c in displays],
                              "reports": 8, "helper_error": 0, "stop_pc": "201D"})
    return summaries


def test_display_report_release(resources):
    card = display_report_ready(resources, address_read_release=False)
    processor = card.processor
    assert conf_display_report_stage(card) == 6
    # Without address-read release, ACK skips the report between displays.
    assert processor.pending.pc == 0x207B and processor.pending.status == 0xE0
    assert len(processor.display_writes) == 9 and not processor.report_mode

    card = display_report_ready(resources)
    card.write(0x20, 0x98)
    card.write(0x0C, 0)
    processor = card.processor
    assert card.read(1) == 0x0B
    capture = processor.pending
    state = processor.cpu.__dict__.copy()
    memory = bytes(card.stream.memory)
    for _ in range(1002):
        assert card.read(1) == 0x0B
    assert processor.cpu.__dict__ == state and bytes(card.stream.memory) == memory
    assert len(processor.display_writes) == 8
    assert card.read(4, 16) == 0x0400
    assert len(processor.display_writes) == 9 and processor.cpu.pc == 0x207B
    rejects(lambda: processor.complete(capture.token))
    assert card.read(4, 16) == 0  # No pending capture; stream opaque read.
    assert len(processor.display_writes) == 9
    assert card.read(1) == 0xE0 and processor.pending.pc == 0x207B
    card.write(0x0C, 0)
    assert card.read(1) == 0x2B
    capture = processor.pending
    memory = bytes(card.stream.memory)
    card.write(0x20, 0x80)
    assert processor.pending.reset and bytes(card.stream.memory) == memory
    assert not processor.report_mode
    rejects(lambda: processor.complete(capture.token))


def keyboard_ready(resources, **options):
    card = display_report_ready(resources, **options)
    assert conf_display_report_stage(card) == 0
    assert conf_c0e8_check(card) == 0
    card.write(0x21, 0)  # Conf $0B4.
    assert conf_c0a0_check(card) == 0
    return card


def test_keyboard_and_vblank(resources):
    summaries = []
    for lane in (0, 1):
        for vector_base in (0x3FFA, 0x7FFA):
            card = keyboard_ready(resources, lane=lane, vector_base=vector_base,
                                  read_reply=0x17)
            processor = card.processor
            pairs = [c for c in processor.captures if c.address in (0xC0E8, 0xC0A0)]
            assert [(c.address, c.write, c.pc, c.status) for c in pairs] == [
                (0xC0E8, True, 0x201D, 0x28), (0xC0E8, False, 0x2020, 0x28),
                (0xC0A0, True, 0x2023, 8), (0xC0A0, False, 0x2026, 9)]
            assert pairs[0].data == 0x17 and pairs[2].data == 0x17
            pending = processor.pending
            state = processor.cpu.__dict__.copy()
            accesses = processor.accesses.copy()
            memory = bytes(card.stream.memory)
            for _ in range(1002):
                assert card.read(1) == 9
                assert card.read(4, 16) == 0xC0A0
            assert processor.pending is pending and processor.cpu.__dict__ == state
            assert processor.accesses == accesses and bytes(card.stream.memory) == memory
            rejects(lambda: card.write(0x19, 0))
            rejects(lambda: card.read(0x0C))
            start = len(processor.captures)
            assert conf_keyboard_check(card) == 0
            reports = processor.captures[start:]
            assert [(c.pc, c.data, c.status) for c in reports] == [
                (0x20AF, 0xA0, 0xE0), (0x20B5, 0x80, 0xE0),
                (0x20BB, 0x20, 0xE0), (0x20C1, 0, 0xE0)]
            assert processor.keyboard == 0x20 and card.control == 0
            expected_memory = bytearray(memory)
            expected_memory[(lane << 16) | 0x1FE] = 0x2B
            assert card.stream.memory == expected_memory
            pending = processor.pending
            state = processor.cpu.__dict__.copy()
            accesses = processor.accesses.copy()
            for _ in range(1002):
                assert card.read(1) == 0xE0
                assert card.read(0x0C) == 0
                assert card.read(4, 16) == 0xC07D
            assert processor.pending is pending and processor.cpu.__dict__ == state
            assert processor.accesses == accesses and card.stream.memory == expected_memory
            start = len(processor.captures)
            assert conf_vblank_check(card) == 0
            vblank = processor.captures[start:]
            assert [(c.pc, c.data, c.status) for c in vblank] == [
                (0x211A, 0x80, 0xE0), (0x2120, 0, 0xE0)]
            assert card.control == 0 and processor.cpu.sp == 0xFD
            expected_memory[(lane << 16) | 0x1FE] = 0x2E
            assert card.stream.memory == expected_memory
            last = processor.pending
            card.write(0x0C, 0)
            rejects(lambda: processor.complete(last.token))
            processor.attempt()  # RTS from $2117.
            assert processor.cpu.pc == 0x202F and processor.cpu.sp == 0xFF
            state = processor.cpu.__dict__.copy()
            accesses = processor.accesses.copy()
            memory = bytes(card.stream.memory)
            for _ in range(2):
                rejects(lambda: card.read(1), ExecutionLimit)
            assert processor.cpu.__dict__ == state and processor.accesses == accesses
            assert bytes(card.stream.memory) == memory
            summaries.append({"lane": lane, "vector_base": f"{vector_base:04X}",
                              "c0e8_statuses": ["28", "28"], "c0a0_statuses": ["08", "09"],
                              "keyboard_reports": [c.data for c in reports],
                              "vblank_reports": [c.data for c in vblank], "stop_pc": "202F"})
    return summaries


def test_keyboard_vblank_faults(resources):
    card = keyboard_ready(resources)
    original_write = card.write

    def corrupt_key(offset, value, width=8):
        original_write(offset, 0xC5 if offset == 0x18 else value, width)

    card.write = corrupt_key
    assert conf_keyboard_check(card) == 9
    assert card.processor.pending.data == 0xC5
    assert card.processor.pending.pc == 0x20AF

    for helper, bit, error in ((conf_keyboard_check, 0x80, 9),
                               (conf_vblank_check, 0x40, 10)):
        card = keyboard_ready(resources)
        if helper is conf_vblank_check:
            assert conf_keyboard_check(card) == 0
        original_write = card.write

        def suppress_control(offset, value, width=8):
            original_write(offset, value & ~bit if offset == 0x0D else value, width)

        card.write = suppress_control
        assert helper(card) == error
        assert card.processor.pending.address == 0xC07D
        assert card.processor.cpu.pc == (0x20B5 if bit == 0x80 else 0x211A)
        old = card.processor.pending
        card.write(0x21, 0xFC)
        card.write(0x20, 0x80)
        assert card.processor.pending.reset and card.processor.keyboard == 0
        rejects(lambda: card.processor.complete(old.token))


def test_display_cancellation_and_fault(resources):
    card = synced(resources)
    assert conf_initial_handshake(card) == 0
    card.write(0x0D, 0)
    card.write(0x0C, 0)
    assert card.read(1) == 0x0A
    processor = card.processor
    capture = processor.pending
    memory = bytes(card.stream.memory)
    card.write(0x20, 0x80)
    assert processor.pending.reset
    assert bytes(card.stream.memory) == memory and processor.display_writes == []
    rejects(lambda: processor.complete(capture.token))

    card = synced(resources)
    assert conf_initial_handshake(card) == 0
    card.write(0x0D, 0)
    original_write = card.write

    def suppress_display_release(offset, value, width=8):
        capture = card.processor.pending
        if offset == 0x0C and capture and capture.address == 0x0400:
            return
        original_write(offset, value, width)

    card.write = suppress_display_release
    assert conf_display_check(card) == 3
    assert card.processor.pending.address == 0x0400
    assert card.processor.display_writes == []


def test_suspension(resources):
    card = uploaded(resources)
    start(card)
    processor = card.processor
    for stage, status in (("reset", 0x80), ("read", 0xE1), ("write", 0xE0)):
        if stage == "read":
            assert conf_reset_sync(card, max_attempts=1) == 0
            assert card.read(1) == 0xE1
        elif stage == "write":
            card.write(0x19, 0)
            assert card.read(1) == 0xE0
        capture = processor.pending
        state = processor.cpu.__dict__.copy()
        accesses = processor.accesses.copy()
        retired = processor.retired.copy()
        memory_hash = hashlib.sha256(card.stream.memory).digest()
        for _ in range(1002):
            assert card.read(1) == status
            assert card.read(4, 16) == capture.address
            assert processor.run_until_capture() is capture
        assert processor.cpu.__dict__ == state
        assert processor.accesses == accesses and processor.retired == retired
        assert hashlib.sha256(card.stream.memory).digest() == memory_hash
        assert processor.pending is capture
        rejects(lambda: card.write(0x19 if stage != "read" else 0x0C, 0))
        rejects(lambda: processor.complete(capture.token + 1))
        assert processor.pending is capture
    card.write(0x0C, 0)
    rejects(lambda: processor.complete(capture.token))
    rejects(lambda: uploaded(resources).write(0x0C, 0))
    assert sum(a[0] and a[1] == 0xC07D for a in processor.accesses) == 1


def test_data_and_reset(resources):
    for value in (0, 0x17, 0x80, 0xFF):
        card = synced(resources, read_reply=value)
        assert conf_initial_handshake(card) == 0
        processor = card.processor
        old = processor.pending
        assert old.data == value
        card.write(0x20, 0x80)
        assert processor.pending.reset and processor.pending.token > old.token
        rejects(lambda: processor.complete(old.token))
        assert not any(write for write, addr, data in processor.accesses if addr == 0xC07D)
        assert conf_reset_sync(card, max_attempts=1) == 0
        assert conf_initial_handshake(card) == 0
        card.write(0x0C, 0)
        assert processor.accesses[-1] == (True, 0xC07D, value)
        finish_display(card)


def test_bounds_and_faults(resources):
    card = synced(resources)
    processor = card.processor
    rejects(lambda: processor.run_until_capture(0))
    rejects(lambda: processor.run_until_capture(1), ExecutionLimit)
    assert processor.cpu.pc == 0x200B and processor.pending is None
    assert processor.run_until_capture(1).address == 0xC07D
    assert processor.cpu.pc == 0x200B
    rejects(lambda: processor.complete(processor.pending.token))
    assert processor.pending is not None

    card = uploaded(resources)
    card.stream.memory[0x23FFD] = 0x30
    start(card)
    assert conf_reset_sync(card, max_attempts=1) == 0
    assert card.processor.cpu.pc == 0x3000
    rejects(lambda: card.read(1), ExecutionLimit)

    card = synced(resources)
    card.stream.memory[0x2000] = 0
    rejects(lambda: card.read(1), ExecutionLimit)
    assert card.processor.retired == []

    card = synced(resources)
    # Suppressing the proposed release cannot manufacture the E0 event.
    original_write = card.write
    card.write = lambda off, data, width=8: None if off == 0x19 else original_write(off, data, width)
    assert conf_initial_handshake(card) == 7
    assert card.processor.pending.pc == 0x200B
    assert card.processor.retired == [0x2000]

    card = synced(resources)
    original_read = card.read
    consumed = False

    def destructive_status(offset, width=8):
        nonlocal consumed
        if (offset, width) == (1, 8):
            if consumed:
                return 0
            consumed = True
        return original_read(offset, width)

    card.read = destructive_status
    assert conf_wait(card) == (2, 0)
    assert card.processor.pending.pc == 0x200B


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    forks = [ROOT / "local/experiments/firmware-memory/app221/IIe Startup.rsrc",
             ROOT / "local/experiments/startup-runtime/startup/IIe Startup.rsrc"]
    results = []
    for path in forks:
        resources = load_conf_resources(path)
        summaries = test_execution(resources)
        test_suspension(resources)
        test_data_and_reset(resources)
        test_bounds_and_faults(resources)
        test_display_bounds(resources)
        host_checks = test_host_display_and_c0e9(resources)
        test_display_cancellation_and_fault(resources)
        report_checks = test_host_display_reports(resources)
        test_display_report_release(resources)
        keyboard_checks = test_keyboard_and_vblank(resources)
        test_keyboard_vblank_faults(resources)
        results.append({"fork": path.relative_to(ROOT).as_posix(), "mappings": summaries,
                        "host_display_and_c0e9": host_checks,
                        "host_display_reports": report_checks,
                        "host_keyboard_and_vblank": keyboard_checks})
    inputs = [Path(__file__).resolve(), Path(__file__).with_name("diagnostic_cpu.py"),
              Path(__file__).with_name("diagnostic_model.py"),
              Path(__file__).with_name("host_model.py"),
              ROOT / "fixtures/research/software-bringup/inspect_resources.py",
              ROOT / "fixtures/experiments/startup-protocol/evidence.json",
              ROOT / "fixtures/experiments/firmware-memory/metadata.json", *forks]
    dependency = hashlib.sha256()
    sources = sorted((DEPS / "py65").rglob("*.py"))
    for path in sources:
        dependency.update(path.relative_to(DEPS).as_posix().encode("ascii") + b"\0")
        dependency.update(path.read_bytes() + b"\0")
    result = {"scope": "py65 original diagnostic prefix; hypothetical host trap adapter",
              "display_report_hypothesis": "$98 display address reads release stores; reports require ACK",
              "checks_passed_per_fork": 11, "forks_checked": 2,
              "py65_version": "1.2.0", "py65_source_tree_sha256": dependency.hexdigest(),
              "py65_source_files": len(sources), "results": results,
              "inputs_sha256": {p.relative_to(ROOT).as_posix():
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
              "elapsed_seconds": round(time.perf_counter() - started, 3)}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="ascii")
    print(encoded, end="")


if __name__ == "__main__":
    main()
