#!/usr/bin/env python3
import itertools
import unittest
from dataclasses import FrozenInstanceError

from trap_model import Access, BusDriver, Display, TrapModel, classify


class ClassificationTests(unittest.TestCase):
    def test_complete_io_address_space(self):
        # Independent enumerated oracle; display disabled to isolate the I/O table.
        both = set(itertools.chain(range(0xC050, 0xC060), [0xC070],
                                  range(0xC090, 0xC0E0), [0xC0E8, 0xC0E9],
                                  range(0xC0F0, 0xC100), [0xCFFF]))
        write_only = {0xC000, 0xC001, 0xC00C, 0xC00D, 0xC00E, 0xC00F}
        for motor, aux, write in itertools.product((False, True), repeat=3):
            display = Display(text_page=None, motor=motor)
            expected = both | write_only if write else both
            actual = {a for a in range(65536)
                      if classify(Access(a, write, aux=aux), display) == "io"}
            self.assertEqual(actual, expected)

    def test_display_page_bank_mode_matrix(self):
        # Each row supplies explicit positive main/aux ranges before hole removal.
        text = {1: set(range(0x400, 0x800)), 2: set(range(0x800, 0xC00))}
        hires = {1: set(range(0x2000, 0x4000)), 2: set(range(0x4000, 0x6000))}
        visible = {a for a in range(0x6000) if a % 128 < 120}
        cases = [
            (Display(), text[1], set()),
            (Display(text_page=2), text[2], set()),
            (Display(col80=True), text[1], text[1]),
            (Display(col80=True, full_graphics=True), text[1], set()),
            (Display(text_page=None, hires_page=1), hires[1], set()),
            (Display(text_page=None, hires_page=2, double_hires=True), hires[2], hires[2]),
            (Display(text_page=2, hires_page=1, col80=True, double_hires=True),
             text[2] | hires[1], text[2] | hires[1]),
            (Display(text_page=None), set(), set()),
            (Display(hires_page=1, col80=True, double_hires=True, motor=True), set(), set()),
        ]
        for display, main, aux in cases:
            for bank, expected in ((False, main), (True, aux)):
                actual = {a for a in range(0x6001)
                          if classify(Access(a, True, aux=bank), display) == "display"}
                self.assertEqual(actual, expected & visible, (display, bank))
                self.assertTrue(all(classify(Access(a, aux=bank), display) is None
                                    for a in range(0x6001)))

    def test_explicit_edges_holes_and_motor_scope(self):
        display = Display(hires_page=1)
        for a in (0x400, 0x477, 0x480, 0x4F7, 0x500, 0x2000, 0x2077, 0x2080):
            self.assertEqual(classify(Access(a, True), display), "display")
        for a in (0x3FF, 0x478, 0x47F, 0x4F8, 0x4FF, 0x800,
                  0x2078, 0x207F, 0x3FFF, 0x4000, 0x6000):
            self.assertIsNone(classify(Access(a, True), display))
        for a in (0xC050, 0xC05C, 0xC070, 0xC0E8, 0xC0E9):
            self.assertEqual(classify(Access(a), Display(motor=True)), "io")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.model = TrapModel()
        self.bus = BusDriver(self.model)

    def test_delayed_write_and_single_completion(self):
        for delay in (0, 1, 7, 257):
            before = len(self.model.writes)
            retired = self.bus.retired
            self.bus.issue(Access(0x400, True, 0xA5, True), Display(col80=True))
            captured = self.model.pending
            self.assertEqual(captured.access, Access(0x400, True, 0xA5, True))
            self.assertEqual(captured.sampled_data, 0xA5)
            with self.assertRaises(FrozenInstanceError):
                captured.access.data = 0
            for _ in range(delay):
                self.assertIs(self.model.wait(), captured)
                self.assertEqual(self.bus.retired, retired)
                self.assertEqual(len(self.model.writes), before)
                with self.assertRaises(RuntimeError):
                    self.bus.issue(Access(0x401, True, 0x5A))
            self.bus.service(captured.token)
            self.assertEqual(self.bus.retired, retired + 1)
            self.assertEqual(len(self.model.writes), before + 1)
            self.assertEqual(self.model.memory[1][0x400], 0xA5)
            self.assertEqual(self.model.memory[0][0x400], 0)
            with self.assertRaises(RuntimeError):
                self.bus.service(captured.token)
            self.assertEqual(len(self.model.writes), before + 1)

    def test_read_capture_reply_and_repeated_accesses(self):
        self.model.memory[0][0xC090] = 0x33
        for reply in (0x00, 0x80, 0xFF, 0x17):
            before = self.bus.retired
            self.bus.issue(Access(0xC090))
            captured = self.model.pending
            self.assertEqual(captured.sampled_data, 0x33)
            self.model.memory[0][0xC090] = 0x99
            for _ in range(11):
                self.assertEqual(self.model.wait().sampled_data, 0x33)
                self.assertEqual(self.bus.retired, before)
            with self.assertRaises(ValueError):
                self.bus.service(captured.token)
            self.assertIs(self.model.pending, captured)
            self.bus.service(captured.token, reply)
            self.assertEqual(self.bus.last_read, reply)
            self.assertEqual(self.bus.retired, before + 1)
            self.model.memory[0][0xC090] = 0x33
        self.assertEqual(len(self.model.writes), 0)

    def test_reset_pending_read_and_write_rejects_old_service(self):
        for write in (False, True):
            self.bus.issue(Access(0xC090, write, 0xDA))
            old = self.model.pending.token
            self.bus.reset()
            self.assertIsNone(self.model.pending)
            self.assertEqual(self.model.memory[0][0xC090], 0)
            self.assertEqual(self.bus.retired, 0)
            self.assertEqual(len(self.model.writes), 0)
            self.bus.issue(Access(0xC090))
            new = self.model.pending.token
            self.assertGreater(new, old)
            with self.assertRaises(RuntimeError):
                self.bus.service(old, 0x11)
            self.assertEqual(self.model.pending.token, new)
            self.bus.service(new, 0x42)
            self.assertEqual(self.bus.last_read, 0x42)
        self.assertEqual(len(self.model.cancelled), 2)

    def test_local_memory_and_repeated_identical_writes(self):
        for bank, value in ((False, 0x21), (True, 0x43)):
            self.bus.issue(Access(0x1000, True, value, bank))
            self.bus.issue(Access(0x1000, aux=bank))
            self.assertEqual(self.bus.last_read, value)
        tokens = []
        for _ in range(4):
            self.bus.issue(Access(0xC090, True, 0x55))
            tokens.append(self.model.pending.token)
            self.bus.service(tokens[-1])
        self.assertEqual(len(set(tokens)), 4)
        self.assertEqual(len(self.model.writes), 6)
        self.assertEqual(self.bus.retired, 8)

    def test_invalid_service_and_ordering_policy(self):
        with self.assertRaises(RuntimeError):
            self.bus.service(1, 0)
        self.bus.issue(Access(0x400, True, 0x12))
        token = self.model.pending.token
        with self.assertRaises(ValueError):
            self.bus.service(token, 0x33)
        self.assertEqual(self.model.memory[0][0x400], 0)
        self.bus.service(token)
        self.bus.reset()
        self.assertEqual(self.model.memory[0][0x400], 0x12)
        self.assertEqual(len(self.model.writes), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
