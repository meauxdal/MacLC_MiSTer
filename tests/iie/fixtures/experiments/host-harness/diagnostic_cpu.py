#!/usr/bin/env python3
"""Bounded py65 execution with an explicitly hypothetical host trap adapter."""

import sys
from dataclasses import dataclass

from host_model import ROOT, HostStream, Hypothesis


DEPS = ROOT / "local/experiments/host-harness/deps"
sys.path.insert(0, str(DEPS))
from py65.devices.mpu65c02 import MPU


class ExecutionLimit(RuntimeError):
    pass


class Suspended(Exception):
    pass


@dataclass(frozen=True)
class Capture:
    token: int
    address: int
    write: bool
    data: int | None
    pc: int | None
    reset: bool = False
    aux: bool = False
    address_release: bool = False

    @property
    def status(self):
        if self.reset:
            return 0x80
        if self.address == 0xC07D:
            return 0xE0 if self.write else 0xE1
        if self.address == 0xC0E9:
            return 0x38
        if self.address == 0xC0E8:
            return 0x28
        if self.address == 0xC0A0:
            return 8 if self.write else 9
        return {0x0400: 0x02, 0x0800: 0x22, 0x2000: 0x04,
                0x4000: 0x24}[self.address] | (8 if self.aux else 0) | int(self.address_release)


class DiagnosticCPU:
    # Traps remain confined to reset and absolute LDA/STA.
    OPCODES = {0x4C, 0xAD, 0x8D, 0x20, 0x60}

    def __init__(self, stream, *, lane=0, vector_base=0x3FFA):
        if lane not in (0, 1) or vector_base not in (0x3FFA, 0x7FFA):
            raise ValueError("unsupported candidate mapping")
        self.stream = stream
        self.lane = lane
        self.vector_base = vector_base
        self.pending = None
        self.serial = 0
        self.resetting = False
        self.permit = None
        self.accesses = []
        self.captures = []
        self.retired = []
        self.aux_write = False
        self.display_writes = []
        self.bank_writes = []
        self.report_mode = False
        self.keyboard = 0
        self.cpu = MPU(memory=self, pc=0)

    def mapped(self, address, write=False):
        if address < 0xC000:
            lane = self.lane ^ int(write and self.aux_write and address >= 0x0200)
            return (lane << 16) | address
        if address >= 0xFFFA:
            return 0x20000 | (self.vector_base + address - 0xFFFA)
        raise ValueError(f"unmodeled CPU address ${address:04X}")

    def access(self, address, write=False, data=None):
        display = write and address in (0x0400, 0x0800, 0x2000, 0x4000)
        trapped = (address in (0xC07D, 0xC0E8, 0xC0E9, 0xC0A0)
                   or (display and self.stream.control == 0)
                   or (self.resetting and address == 0xFFFC))
        if trapped:
            if self.permit is None:
                self.serial += 1
                self.pending = Capture(self.serial, address, write, data,
                                       None if self.resetting else self.cpu.pc - 1,
                                       self.resetting, self.aux_write if display else False,
                                       display and self.report_mode)
                self.captures.append(self.pending)
                raise Suspended
            capture, reply = self.permit
            if (address, write, data) != (capture.address, capture.write, capture.data):
                raise RuntimeError("replayed access differs from capture")
            self.permit = None
            value = data if write else reply
        elif not write:
            if address == 0xC000:
                value = self.keyboard
            elif address == 0xC010:
                value = self.stream.control & 0x80
                self.keyboard &= 0x7F
            elif address == 0xC019:
                value = (self.stream.control & 0x40) << 1
            else:
                value = self.stream.memory[self.mapped(address)]
        if write:
            if address in (0xC004, 0xC005):
                self.aux_write = address == 0xC005
                self.bank_writes.append((address, data))
            elif 0x0100 <= address < 0x0200 or address in (0x0400, 0x0800, 0x2000, 0x4000):
                mapped = self.mapped(address, write=True)
                self.stream.memory[mapped] = data
                if address >= 0x0200:
                    self.display_writes.append((address, mapped, data))
            elif address not in (0xC07D, 0xC0E8, 0xC0E9, 0xC0A0):
                raise ValueError("CPU write outside stack/display boundary")
            value = data
        self.accesses.append((write, address, value))
        return value

    def __getitem__(self, address):
        return self.access(address)

    def __setitem__(self, address, data):
        self.access(address, True, data)

    def reset(self):
        self.pending = None
        self.permit = None
        self.resetting = True
        self.aux_write = False
        self.report_mode = False
        self.keyboard = 0
        self.cpu.start_pc = None
        self.attempt()

    def attempt(self):
        state = self.cpu.__dict__.copy()
        access_count = len(self.accesses)
        pc = self.cpu.pc
        if not self.resetting:
            if pc == 0x202F:
                raise ExecutionLimit("keyboard/vblank prefix complete; NOP/IRQ is unsupported")
            opcode = self.stream.memory[self.mapped(pc)]
            if opcode not in self.OPCODES:
                raise ExecutionLimit(f"unmodeled instruction at ${pc:04X}")
        try:
            if self.resetting:
                self.cpu.reset()
            else:
                self.cpu.step()
        except Suspended:
            # Only reset/LDA/STA can suspend, before any committed write.
            self.cpu.__dict__.update(state)
            del self.accesses[access_count:]
            return
        if not self.resetting:
            self.retired.append(pc)
        self.resetting = False

    def run_until_capture(self, max_instructions=16):
        if max_instructions < 1:
            raise ValueError("max_instructions must be positive")
        for _ in range(max_instructions):
            if self.pending is not None:
                return self.pending
            self.attempt()
        if self.pending is not None:
            return self.pending
        raise ExecutionLimit("CPU instruction budget exhausted")

    def complete(self, token, read_data=None):
        capture = self.pending
        if capture is None or token != capture.token:
            raise ValueError("stale or unsolicited completion")
        if capture.write:
            if read_data is not None:
                raise ValueError("write completion has no read data")
        elif capture.reset:
            if read_data is not None:
                raise ValueError("reset uses the uploaded vector")
            read_data = self.stream.memory[self.mapped(capture.address)]
        elif read_data is None or not 0 <= read_data <= 255:
            raise ValueError("read completion requires a byte")
        self.permit = (capture, read_data)
        self.pending = None
        self.attempt()
        if self.permit is not None or self.pending is not None:
            raise RuntimeError("completion failed to retire its captured operation")


class DiagnosticCard:
    """Candidate: sticky captures; $98 display address reads optionally release."""

    def __init__(self, *, read_reply=0xA5, lane=0, vector_base=0x3FFA,
                 address_read_release=True):
        if not 0 <= read_reply <= 255:
            raise ValueError("read reply must be a byte")
        self.stream = HostStream(Hypothesis("diagnostic CPU candidate"), self.opaque)
        self.processor = DiagnosticCPU(self.stream, lane=lane, vector_base=vector_base)
        self.read_reply = read_reply
        self.reset_mask = None
        self.armed = False
        self.events = []
        self.address_read_release = address_read_release

    @property
    def control(self):
        return self.stream.control

    @staticmethod
    def opaque(offset, width):
        if (offset, width) not in ((0x08, 8), (0x04, 16)):
            raise ValueError("unsupported opaque read")
        return 0

    def read(self, offset, width=8):
        processor = self.processor
        release = None
        if (offset, width) == (1, 8):
            capture = processor.pending
            if capture is None and self.armed and self.control & 3 in (0, 3):
                capture = processor.run_until_capture()
            value = capture.status if capture else 0
        elif (offset, width) == (0x0C, 8) and processor.pending is not None:
            if not processor.pending.write:
                raise ValueError("data read requires a captured write")
            value = processor.pending.data
        elif (offset, width) == (0x09, 8):
            value = processor.keyboard & 0x80
        elif (offset, width) == (4, 16) and processor.pending is not None:
            value = processor.pending.address
            if processor.pending.address_release and self.address_read_release:
                release = processor.pending
        else:
            value = self.stream.read(offset, width)
        self.events.append([False, width, offset, value])
        if release is not None:
            processor.complete(release.token)
        return value

    def write(self, offset, value, width=8):
        if not 0 <= value < (1 << width):
            raise ValueError("write exceeds transfer width")
        processor = self.processor
        capture = processor.pending
        if (offset, width) == (0x21, 8):
            self.reset_mask = value
        elif (offset, width) == (0x18, 8):
            processor.keyboard = value
        elif (offset, width) == (0x20, 8):
            if value == 0x80 and self.reset_mask == 0xFC:
                self.armed = False
                processor.reset()
            elif value == 0x88 and capture is not None and capture.reset:
                self.armed = True
            elif value in (0x88, 0x98) and self.armed:
                processor.report_mode = value == 0x98
            else:
                raise ValueError("unsupported CPU control sequence")
        elif (offset, width) in ((0x0C, 8), (0x19, 8)):
            if capture is None and self.armed:
                capture = processor.run_until_capture()
            if value != 0 or capture is None:
                raise ValueError("release without pending capture")
            expected = 0x19 if capture.address == 0xC07D and not capture.write else 0x0C
            if offset != expected or (capture.reset and not self.armed):
                raise ValueError("wrong release for pending capture")
            processor.complete(capture.token, self.read_reply
                               if not capture.reset and not capture.write else None)
        elif offset in (0x20, 0x21):
            raise ValueError("unsupported CPU control width")
        else:
            self.stream.write(offset, value, width)
        self.events.append([True, width, offset, value])
