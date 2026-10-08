"""Convert the bench's PPM reconstructions to PNG and a local review gallery.

Uses Python's standard library; it does not alter pixels or rescale fields.
Individual fields have half the frame height and retain their native row order.
"""
import argparse
import hashlib
import html
import json
import struct
import zlib
from pathlib import Path


def audit_waveforms(out: Path) -> str:
    """Measure actual VCD edge times, separately from the sample-count oracle."""
    windows = sorted(out.glob("steady*_sync.vcd"))
    if len(windows) != 4:
        raise RuntimeError(f"Expected four current waveform windows, got {len(windows)}")
    widths = [62] * 6 + [731] * 6 + [62] * 6
    lines = []
    for path in windows:
        symbols = {}
        edges = []
        timestamp = 0
        previous = None
        with path.open() as stream:
            for line in stream:
                words = line.split()
                if words[:1] == ["$var"] and words[4] not in symbols:
                    symbols[words[4]] = words[3]
                if words[:1] == ["$timescale"] and words[1] != "1ps":
                    raise RuntimeError(f"Unexpected VCD timescale: {path}")
                if line.startswith("#"):
                    timestamp = int(line[1:])
                if symbols.get("csync_n") and line.strip() in (
                        "0" + symbols["csync_n"], "1" + symbols["csync_n"]):
                    value = int(line[0])
                    if value != previous:
                        edges.append((timestamp, value))
                        previous = value
        lows = []
        start = None
        for timestamp, value in edges:
            if value == 0:
                start = timestamp
            elif start is not None:
                lows.append((start, timestamp - start))
                start = None
        if len(lows) < 18:
            raise RuntimeError(f"Incomplete vertical pulse sequence: {path}")
        for pulse, ticks in enumerate(widths):
            if abs(lows[pulse][1] - ticks * 1_000_000 / 27) > 1:
                raise RuntimeError(f"VCD pulse width mismatch: {path}, pulse {pulse}")
            if pulse and abs(lows[pulse][0] - lows[pulse - 1][0] - 858 * 1_000_000 / 27) > 1:
                raise RuntimeError(f"VCD half-line spacing mismatch: {path}, pulse {pulse}")
        lines.append(f"PASS {path.name}: 6 equalizing, 6 broad, 6 equalizing pulses; half-line spacing")
    result = "\n".join(lines) + "\nMeasured widths: 2.296296 / 27.074074 us; spacing: 31.777778 us (<=1 ps rounding)\n"
    (out / "waveform_audit.txt").write_text(result)
    return result


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def convert(source: Path) -> Path:
    with source.open("rb") as stream:
        if stream.readline() != b"P6\n":
            raise ValueError(f"Unexpected PPM magic: {source}")
        width, height = map(int, stream.readline().split())
        if stream.readline() != b"255\n":
            raise ValueError(f"Unexpected PPM depth: {source}")
        pixels = stream.read()
    if width != 640 or height not in (240, 480) or len(pixels) != width * height * 3:
        raise ValueError(f"Unexpected PPM dimensions/data: {source}")
    rows = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    result = (b"\x89PNG\r\n\x1a\n"
              + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
              + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))
    target = source.with_suffix(".png")
    target.write_bytes(result)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    out = parser.parse_args().directory
    report = (out / "verification.txt").read_text()
    if not report.startswith("PASS:"):
        raise RuntimeError("Refusing to label a failed bench's images as verified")
    waveforms = audit_waveforms(out)
    pictures = [convert(path) for path in sorted(out.glob("g*.ppm"))]
    if len(pictures) != 48:
        raise RuntimeError(f"Expected 48 reconstructed images, got {len(pictures)}")
    cards = "\n".join(
        f'<figure><figcaption>{html.escape(path.stem)}</figcaption>'
        f'<img src="{html.escape(path.name)}" width="640" alt="{html.escape(path.stem)}"></figure>'
        for path in pictures)
    (out / "gallery.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<title>TV525 Stage 1 verification</title><style>'
        'body{background:#202124;color:#eee;font:16px system-ui;margin:24px}'
        'main{display:flex;flex-wrap:wrap;gap:20px}figure{margin:0;max-width:100%}'
        'img{max-width:100%;height:auto;image-rendering:pixelated}figcaption{margin:8px 0}'
        'pre{white-space:pre-wrap}</style><h1>TV525 Stage 1 simulation</h1>'
        '<p>Woven frames are 640×480; separate fields are 640×240. '
        'These are digital simulations, not photographs or analog-output qualification.</p>'
        f'<pre>{html.escape(report + waveforms)}</pre><main>{cards}</main></html>', encoding="utf-8")
    root = Path(__file__).resolve().parent.parent
    sources = ["rtl/tv525_timing.sv", "rtl/tv_test_pattern.sv", "verilator/tv525_diagnostic.sv",
               "verilator/tb_tv525.cpp", "verilator/render_tv525.py", "verilator/Makefile"]
    (out / "source_manifest.json").write_text(json.dumps(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
        indent=2) + "\n")
    print(f"Rendered {len(pictures)} PNGs and {out / 'gallery.html'}")
    print("PASS: measured vertical pulse widths/spacing in all four VCD windows")


if __name__ == "__main__":
    main()
