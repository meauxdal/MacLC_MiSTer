#!/usr/bin/env python3
"""Synthetic 16-sector WOZ2 media and nibble decoding for IWM backend checks."""
import struct
import zlib

TRACKS = 35
TRACK_BLOCKS = 13
NIBBLES = bytes.fromhex(
    '96979a9b9d9e9fa6a7abacadaeafb2b3b4b5b6b7b9babbbcbdbebfcbcdcecfd3'
    'd6d7d9dadbdcdddedfe5e6e7e9eaebecedeeeff2f3f4f5f6f7f9fafbfcfdfeff')
DECODE = {b: i for i, b in enumerate(NIBBLES)}
VOLUME = 0xFE


def sector_data(track, sector):
    return bytes((track * 37 + sector * 11 + i * 7 + (i >> 3)) & 0xFF for i in range(256))


def encode62(data):
    values = []
    for i in range(86):
        v = 0
        for k, j in enumerate((i, i + 86, i + 172)):
            if j < 256:
                b = data[j]
                v |= (((b & 1) << 1) | ((b >> 1) & 1)) << (2 * k)
        values.append(v)
    values += [b >> 2 for b in data]
    out, prev = [], 0
    for v in values:
        out.append(NIBBLES[v ^ prev])
        prev = v
    out.append(NIBBLES[prev])
    return bytes(out)


def decode62(nibbles):
    values, prev = [], 0
    for n in nibbles[:342]:
        prev ^= DECODE[n]
        values.append(prev)
    if prev ^ DECODE[nibbles[342]]:
        raise ValueError('data checksum')
    data = bytearray(v << 2 for v in values[86:])
    for i in range(86):
        for k, j in enumerate((i, i + 86, i + 172)):
            if j < 256:
                bits = (values[i] >> (2 * k)) & 3
                data[j] |= ((bits & 1) << 1) | (bits >> 1)
    return bytes(data)


def four_four(v):
    return bytes(((v >> 1) | 0xAA, v | 0xAA))


def track_bits(track):
    bits = []
    def sync(count):
        for _ in range(count):
            bits.extend([1] * 8 + [0, 0])
    def put(data):
        for b in data:
            bits.extend((b >> (7 - i)) & 1 for i in range(8))
    sync(48)
    for sector in range(16):
        put(b'\xd5\xaa\x96' + four_four(VOLUME) + four_four(track) + four_four(sector) +
            four_four(VOLUME ^ track ^ sector) + b'\xde\xaa\xeb')
        sync(6)
        put(b'\xd5\xaa\xad' + encode62(sector_data(track, sector)) + b'\xde\xaa\xeb')
        sync(16)
    return bits


def write_schedule(track, salt):
    """Nibbles and CPU cycles to the next load: 40-cycle self-sync, 32 otherwise."""
    out = []
    def sync(count):
        out.extend((0xFF, 40) for _ in range(count))
    def put(data):
        out.extend((b, 32) for b in data)
    sync(16)
    for sector in range(16):
        put(b'\xd5\xaa\x96' + four_four(VOLUME) + four_four(track) + four_four(sector) +
            four_four(VOLUME ^ track ^ sector) + b'\xde\xaa\xeb')
        sync(6)
        put(b'\xd5\xaa\xad' + encode62(sector_data(track + salt, sector)) + b'\xde\xaa\xeb')
        sync(8)
    return out


def build_woz():
    info = struct.pack('<BBBBB32sBBBHHH', 2, 1, 0, 0, 1, b'MacLC IWM check'.ljust(32), 1, 1, 32, 0, 0,
                       TRACK_BLOCKS).ljust(60, b'\0')
    tmap = bytearray([0xFF] * 160)
    for t in range(TRACKS):
        for q in (4 * t - 1, 4 * t, 4 * t + 1):
            if 0 <= q < 160:
                tmap[q] = t
    entries, data = bytearray(), bytearray()
    for t in range(TRACKS):
        bits = track_bits(t)
        packed = bytearray((len(bits) + 7) // 8)
        for i, bit in enumerate(bits):
            packed[i >> 3] |= bit << (7 - (i & 7))
        assert len(packed) <= TRACK_BLOCKS * 512
        entries += struct.pack('<HHI', 3 + t * TRACK_BLOCKS, TRACK_BLOCKS, len(bits))
        data += packed.ljust(TRACK_BLOCKS * 512, b'\0')
    entries = entries.ljust(1280, b'\0')
    body = (b'INFO' + struct.pack('<I', 60) + info + b'TMAP' + struct.pack('<I', 160) + tmap +
            b'TRKS' + struct.pack('<I', len(entries) + len(data)) + entries)
    assert 12 + len(body) == 1536
    body += data
    return b'WOZ2\xff\x0a\x0d\x0a' + struct.pack('<I', zlib.crc32(body)) + body


def sectors(stream):
    """Return {(track, sector): data} for complete address/data field pairs."""
    found, i = {}, 0
    while True:
        i = stream.find(b'\xd5\xaa\x96', i)
        if i < 0 or i + 11 > len(stream):
            return found
        f = stream[i + 3:i + 11]
        vol, trk, sec, chk = (((f[k] << 1) | 1) & f[k + 1] for k in range(0, 8, 2))
        j = stream.find(b'\xd5\xaa\xad', i + 11, i + 60)
        if vol ^ trk ^ sec ^ chk == 0 and j >= 0 and j + 346 <= len(stream):
            found[(trk, sec)] = decode62(stream[j + 3:j + 346])
        i += 3
