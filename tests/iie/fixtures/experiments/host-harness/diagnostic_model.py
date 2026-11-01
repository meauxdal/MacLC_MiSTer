#!/usr/bin/env python3
"""Recovered Conf polling sequence; no CPU or diagnostic status producer."""


class ResetSearchLimit(RuntimeError):
    """Harness bound reached; this is not a Conf timeout or cleanup path."""


def conf_wait(bus):
    """Conf $5E4: return (D0.W error, D2.B status)."""
    bus.read(0x01)
    for _ in range(1001):
        status = bus.read(0x01)
        if status:
            return 0, status
    return 2, 0


def conf_reset_sync(bus, *, max_attempts):
    """Resume at Conf $052; stop before $07C or at guest error cleanup."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for _ in range(max_attempts):
        error, _ = conf_wait(bus)
        if error:
            bus.write(0x20, 0x0802, 16)
            return error
        if bus.read(0x04, 16) == 0xFFFC:
            bus.write(0x20, 0x88)
            bus.write(0x0C, 0)
            bus.write(0x0D, 3)
            return 0
        bus.write(0x0C, 0)
    raise ResetSearchLimit("Conf reset-address search remains pending")


def conf_initial_handshake(bus):
    """Conf $364 helper only; the caller owns common error cleanup."""
    error, status = conf_wait(bus)
    if error:
        return error
    if status != 0xE1:
        return 7
    bus.write(0x19, 0)
    error, status = conf_wait(bus)
    if error:
        return error
    return 0 if status == 0xE0 else 7


def conf_display_check(bus):
    """Conf $3E6 helper; WAIT errors become status mismatches."""
    for expected in (0x0A, 0x2A, 0x0C, 0x2C, 0x02, 0x22, 0x04, 0x24):
        bus.write(0x0C, 0)
        _, status = conf_wait(bus)
        if status != expected:
            return 3
    return 0


def conf_c0e9_check(bus):
    """Conf $2DC helper; WAIT errors become status mismatches."""
    for _ in range(2):
        bus.write(0x0C, 0)
        _, status = conf_wait(bus)
        if status != 0x38:
            return 5
    return 0


def conf_c0e8_check(bus):
    """Conf $2B8; WAIT errors become status mismatches."""
    for _ in range(2):
        bus.write(0x0C, 0)
        _, status = conf_wait(bus)
        if status != 0x28:
            return 4
    return 0


def conf_c0a0_check(bus):
    """Conf $388; preserve WAIT errors, unlike the C0E8/C0E9 helpers."""
    for expected in (8, 9):
        bus.write(0x0C, 0)
        error, status = conf_wait(bus)
        if error:
            return error
        if status != expected:
            return 8
    return 0


def conf_keyboard_check(bus):
    """Conf $244-$2B6; failure leaves the control bits as the guest does."""
    bus.write(0x18, 0xA0)
    if not bus.read(0x09) & 0x80:
        return 9
    bus.write(0x0D, bus.read(0x0D) | 0x80)
    for index in range(4):
        bus.write(0x0C, 0)
        error, _ = conf_wait(bus)
        if error:
            return error
        data = bus.read(0x0C)
        if index == 0 and data != 0xA0:
            return 9
        if index == 1:
            if not data & 0x80:
                return 9
            bus.write(0x0D, bus.read(0x0D) & 0x7F)
            if bus.read(0x09) & 0x80:
                return 9
        if index == 2 and data != 0x20:
            return 9
        if index == 3 and data & 0x80:
            return 9
    return 0


def conf_vblank_check(bus):
    """Conf $3B0-$3E4; bit 6 is cleared only after the first data check."""
    bus.write(0x0D, bus.read(0x0D) | 0x40)
    for index in range(2):
        bus.write(0x0C, 0)
        error, _ = conf_wait(bus)
        if error:
            return error
        data = bus.read(0x0C)
        if bool(data & 0x80) != (index == 0):
            return 10
        if index == 0:
            bus.write(0x0D, bus.read(0x0D) & 0xBF)
    return 0


def conf_display_report_check(bus):
    """Conf $148; address reads overwrite D0, intermediate WAITs are unchecked."""
    statuses = (0x0B, 0x2B, 0x0D, 0x2D, 0x03, 0x23, 0x05, 0x25)
    for index, expected in enumerate(statuses):
        bus.write(0x0C, 0)
        _, status = conf_wait(bus)
        bus.read(0x04, 16)
        if status != expected:
            return 6
        if index < len(statuses) - 1:
            conf_wait(bus)
    return 0


def conf_display_report_stage(bus):
    """Conf $098-$0AA, including mode restoration on helper failure."""
    bus.write(0x20, 0x98)
    error = conf_display_report_check(bus)
    bus.write(0x20, 0x88)
    return error
