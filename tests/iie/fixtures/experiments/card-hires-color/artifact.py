#!/usr/bin/env python3
"""Reconstructed CODE 5 waveform latch, not a physical NTSC model."""

COLORS = (15, 3, 6, 5, 9, 14, 13, 7, 10, 2, 12, 4, 8, 1, 11, 0)

# Phase-relative hold/replace decisions for the four-sample lookahead pattern.
REPLACE = (0xaaab, 0xa8aa, 0xaaae, 0xa0a8, 0x0011, 0x88a8, 0x0044, 0x55d5,
           0xabaa, 0x2200, 0x1511, 0x8800, 0x1505, 0x7555, 0x5515, 0xd555)


def rotate(value, amount):
    amount %= 4
    return ((value >> amount) | (value << (4 - amount))) & 15


def decode(window):
    assert 0 <= window < 2048
    samples = [(window >> (10 - bit)) & 1 for bit in range(11)]
    state = 15 if samples[0] else 0
    pixels = []
    for position in range(8):
        phase_state = rotate(state, position)
        future = sum(samples[position + bit] << bit for bit in range(4))
        if (REPLACE[phase_state] >> future) & 1:
            phase_state = future
        state = rotate(phase_state, -position)
        if position >= 4:
            color = state ^ 15 if state in (5, 10) else state
            pixels.append(COLORS[color])
    return pixels


def table_image():
    return b''.join(sum(color << (12 - i * 4) for i, color in enumerate(decode(window))).to_bytes(2, 'big')
                    for window in range(2048))
