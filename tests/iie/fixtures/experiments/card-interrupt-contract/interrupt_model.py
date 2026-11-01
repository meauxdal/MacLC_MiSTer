#!/usr/bin/env python3
"""Hand-authored Conf $200-$242 replay; no interrupt or status producer."""


def wait(bus):
    bus.read(1)
    for _ in range(1001):
        status = bus.read(1)
        if status:
            return 0, status
    return 2, 0


def conf_interrupt_check(bus):
    bus.write(0x0C, 0)
    error, _ = wait(bus)
    if error or bus.read(0x0C) != 2:
        return 11
    bus.write(0x0C, 0)
    bus.write(0x20, bus.read(0x20) | 0x20)
    error, _ = wait(bus)
    # Conf clears the command bit even when this WAIT timed out.
    bus.write(0x20, bus.read(0x20) & 0xDF)
    if error:
        return 12
    bus.write(0x0C, 0)
    error, _ = wait(bus)
    return 12 if error else 0
