#!/usr/bin/env python3
"""Recovered Conf helpers; the bus supplies actual status and captured data."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'fixtures/experiments/host-harness'))
from diagnostic_model import conf_wait


def conf_softswitch_check(bus):
    """Conf $300-$338: sixteen stops, with two aggregate state checks."""
    for expected in (0xFF, 0):
        for _ in range(8):
            bus.write(0x0C, 0)
            error, _ = conf_wait(bus)
            if error:
                return 15
        if bus.read(0x08) != expected:
            return 15
    return 0


def conf_finish(bus):
    """Conf $0E6-$106: final captured data is read, then D0 is cleared."""
    error = conf_softswitch_check(bus)
    if not error:
        bus.write(0x0C, 0)
        error, _ = conf_wait(bus)
        if not error:
            bus.read(0x0C)
    bus.write(0x20, 0x0802, 16)
    return error
