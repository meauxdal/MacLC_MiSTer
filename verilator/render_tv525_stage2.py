"""Render exact composed-RGB captures and pin/CDC simulation source identity."""
from pathlib import Path
import hashlib
import html
import json
import sys
from render_tv525 import convert

out = Path(sys.argv[1] if len(sys.argv) > 1 else "out/tv525_stage2")
captures = [path for path in sorted(out.glob("*.ppm")) if "_field" not in path.stem]
images = []
for path in captures:
    images.append(convert(path))
    with path.open("rb") as stream:
        if [stream.readline() for _ in range(3)] != [b"P6\n", b"640 480\n", b"255\n"]:
            raise ValueError(f"Unexpected capture: {path}")
        pixels = stream.read()
    for parity in range(2):
        field = path.with_name(path.stem + f"_field{parity}.ppm")
        field.write_bytes(b"P6\n640 240\n255\n" + b"".join(
            pixels[y*640*3:(y+1)*640*3] for y in range(parity, 480, 2)))
        images.append(convert(field))
root = Path(__file__).resolve().parent.parent
sources = ["rtl/tv525_timing.sv", "rtl/tv_test_pattern.sv", "rtl/tv525_output.sv",
           "rtl/tv_osd.sv", "rtl/tv_component.sv", "rtl/tv_component_pins.sv",
           "verilator/tb_tv_component.cpp", "verilator/tb_tv525_output.cpp",
           "verilator/render_tv525_stage2.py", "verilator/render_tv525.py", "verilator/Makefile"]
(out / "source_manifest.json").write_text(json.dumps({
    name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources
}, indent=2) + "\n")
(out / "gallery.html").write_text(
    '<!doctype html><meta charset="utf-8"><title>TV525 Stage 2</title>'
    '<style>body{background:#222;color:#eee;font:16px sans-serif}img{max-width:100%}'
    'figure{display:inline-block}pre{white-space:pre-wrap}</style>'
    '<h1>Stage 2 digital simulation</h1><p>Composed RGB before component conversion. '
    'No FPGA or analog measurements.</p><pre>' + html.escape((out / "verification.txt").read_text()) +
    '</pre>' + ''.join('<figure><figcaption>' + html.escape(p.stem) +
                       '</figcaption><img src="' + p.name + '"></figure>' for p in images))
print(f"Rendered {len(images)} exact composed-RGB images and source SHA-256 manifest")
