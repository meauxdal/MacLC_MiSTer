#!/usr/bin/env python3
"""Transaction-level experiment; no CPU, PDS decoder, or hardware timing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Access:
    address: int
    write: bool = False
    data: int = 0
    aux: bool = False

    def __post_init__(self):
        if not 0 <= self.address <= 0xFFFF or not 0 <= self.data <= 0xFF:
            raise ValueError("address/data out of range")


@dataclass(frozen=True)
class Display:
    # Caller resolves banking, 80STORE, PAGE2, and mixed-mode active pages.
    text_page: int | None = 1
    hires_page: int | None = None
    col80: bool = False
    full_graphics: bool = False
    double_hires: bool = False
    motor: bool = False

    def __post_init__(self):
        if self.text_page not in (None, 1, 2) or self.hires_page not in (None, 1, 2):
            raise ValueError("active page must be None, 1, or 2")


def classify(access, display):
    """TN #10 table/notes; active-page resolution is supplied by the caller."""
    a = access.address
    if (0xC050 <= a <= 0xC05F or a == 0xC070
            or 0xC090 <= a <= 0xC0DF or 0xC0E8 <= a <= 0xC0E9
            or 0xC0F0 <= a <= 0xC0FF or a == 0xCFFF):
        return "io"
    if access.write and (0xC000 <= a <= 0xC001
                         or 0xC00C <= a <= 0xC00F):
        return "io"
    if not access.write or display.motor or (a & 0x7F) >= 0x78:
        return None
    text_page = 1 if 0x400 <= a <= 0x7FF else 2 if 0x800 <= a <= 0xBFF else None
    hires_page = 1 if 0x2000 <= a <= 0x3FFF else 2 if 0x4000 <= a <= 0x5FFF else None
    if text_page is not None and text_page == display.text_page:
        if not access.aux or (display.col80 and not display.full_graphics):
            return "display"
    if hires_page is not None and hires_page == display.hires_page:
        if not access.aux or display.double_hires:
            return "display"
    return None


@dataclass(frozen=True)
class Pending:
    token: int
    access: Access
    reason: str
    sampled_data: int


@dataclass(frozen=True)
class Completion:
    token: int
    access: Access
    data: int | None


class TrapModel:
    def __init__(self):
        self.memory = [bytearray(65536), bytearray(65536)]
        self.pending = None
        self.serial = 0
        self.completions = []
        self.writes = []
        self.cancelled = []

    def begin(self, access, display):
        if self.pending is not None:
            raise RuntimeError("pending access blocks new requests")
        self.serial += 1
        sampled = access.data if access.write else self.memory[access.aux][access.address]
        reason = classify(access, display)
        request = Pending(self.serial, access, reason or "local", sampled)
        if reason is not None:
            self.pending = request
            return None
        return self._commit(request, sampled)

    def wait(self):
        # One synthetic wait tick; no real clock or bus phase is represented.
        return self.pending

    def finish(self, token, read_data=None):
        request = self.pending
        if request is None or token != request.token:
            raise RuntimeError("stale or unsolicited completion")
        if request.access.write:
            if read_data is not None:
                raise ValueError("write completion has no read reply")
        elif read_data is None or not 0 <= read_data <= 255:
            raise ValueError("trapped read requires a byte reply")
        result = self._commit(request, read_data)
        self.pending = None
        return result

    def _commit(self, request, read_data):
        access = request.access
        if access.write:
            self.memory[access.aux][access.address] = access.data
            self.writes.append((request.token, access))
        result = Completion(request.token, access, None if access.write else read_data)
        self.completions.append(result)
        return result

    def reset(self):
        # Experiment policy: cancel uncommitted request; retain RAM and token epoch.
        if self.pending is not None:
            self.cancelled.append(self.pending)
        self.pending = None


class BusDriver:
    """Self-authored bus requests and retirement counter, not instruction execution."""

    def __init__(self, model):
        self.model = model
        self.retired = 0
        self.last_read = None

    def issue(self, access, display=Display()):
        result = self.model.begin(access, display)
        if result is not None:
            self._retire(result)
        return result

    def service(self, token, read_data=None):
        result = self.model.finish(token, read_data)
        self._retire(result)
        return result

    def _retire(self, result):
        self.retired += 1
        if not result.access.write:
            self.last_read = result.data

    def reset(self):
        self.model.reset()
        self.retired = 0
        self.last_read = None
