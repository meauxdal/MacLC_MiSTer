# CRT de-flicker experiment

Hardware description: roughly three stationary curved moire bands, bowing to
the right, flicker rapidly on the desktop. Other content generally looks good.
This remains an observation to investigate, not a proven sync or dithering
diagnosis. This experiment changes picture filtering only.

## Controls and implementation

The TV build adds `O12,CRT De-flicker,Off,Mild,Strong` on previously unused
status bits 2:1. Off is the default. The two-flop native-domain control is
latched at each source frame start; filtering never changes within an image.
The displayed image owner still holds that complete image across both fields.

`rtl/tv_deflicker.sv` processes progressive RGB before the existing CRT capture
packer. Mild computes `(above + 6*center + below + 4)/8` per channel; Strong
computes `(above + 2*center + below + 2)/4`. Value 3 also selects Strong.
The first/last source rows replicate the nearest row. Two rows of history
occupy a synchronous 640 x 48-bit RAM (30,720 logical bits); a delayed write
avoids simultaneous reads/writes to the same column. Actual M10K allocation,
arithmetic fit and timing must be checked in a future FPGA build.

All settings use the same one-row buffering and CE pipeline. Off returns
exact source colors. The final row drains during source vertical blanking;
normal horizontal blanking may be shorter than the image width. Reset,
invalid geometry, malformed rows and interrupted frames invalidate capture.
Old histories are overwritten before being used in the next frame. The
unsupported portrait mode never publishes an image.

The filter is instantiated only under `MAC_TV525_DIAG` in `MacLC.sv`, before
the MT32/HUD/framework overlays. Native HDMI is untouched. There are no
changes to `sys/`, timing/PLL, composite sync, OSD composition, DDR traffic
size, frame ownership, field parity or TV raster pipeline latency. Both source
lists include the module. No Quartus build, deployment, build-stamp change or
commit was performed; the previously recorded restriction on Quartus remains.

## Verification

`make tb_tv_deflicker` checks 8,825,856 exact pixels in 39 complete images
through the real RGBx capture packer. Coverage includes Off/Mild/Strong,
512x342/512x384/640x480, checkerboard, flat RGB, one-pixel horizontal line,
RGB gradients, variable CE gaps, midframe setting changes, missing-pixel
abort, guest reset/recovery and portrait rejection.

The actual V8 pipeline fixture now includes this filter in Off mode. Its
existing regressions pass, including real VRAM/Ariel at all supported depths,
two million live writes per drawing run, exact complete-image identity across
both fields, and zero healthy-run overflow/underrun. The raster/platform test
passes 5,405,400 independent sync/DE checks. Route checks pass for both TV
profiles and confirm the normal profile excludes the filter and HDMI routes
remain unchanged.

Full buffered picture tests are available for each strength:

Both Mild and Strong pass the full DDR/480i tests: all three geometries,
both fields, exact RGB/component output and continuous sync, contention,
source loss/reset, incomplete images, overflow, missed-line fallback, live
geometry changes and divided CE. Healthy runs have zero overflow/underrun;
fault injection exercises whole-line black fallback without raster stalls.

```sh
cd verilator
make tb_tv_deflicker
make tb_tv_frame TV_FRAME_FILTER=1
make tb_tv_frame TV_FRAME_FILTER=2
make tb_tv_v8 tb_tv525_platform
python3 check_tv_frame_routes.py
```

Logs: `scratch/tv_deflicker_regression.log`, `scratch/tv_deflicker_mild.log`,
`scratch/tv_deflicker_strong.log`, `scratch/tv_deflicker_routes.log`.

## Hardware comparison after a build

On the same desktop, select Off, then Strong, then Mild. Allow a few frames
for a completed filtered image to reach the CRT. Strong maps an ideal black/
white one-pixel checkerboard to uniform RGB 128 in interior rows; Mild reduces
the contrast by half. Text and thin horizontal lines soften with filtering.
Neither setting blends successive images, so this introduces no temporal
ghosting. Record whether the stationary bands disappear, weaken or persist.
An improvement demonstrates filtering is useful, not that the physical sync
has been qualified or the underlying cause conclusively identified.

## Quartus 17 RAM inference repair

The user's Oct 8 22:52 failed fit requires 4,730 LABs on a device with 4,191.
The corresponding `MacLC.map.rpt` explicitly lists `crt_filter|rows` as
uninferred due to asynchronous read logic (276007). The filter hierarchy
uses 10,957 combinational ALUTs, 30,870 registers and zero block memory bits.
The original multi-branch read template therefore failed physical inference;
the functional simulations did not establish synthesis correctness.

The repair places the three-way address mux ahead of one enabled synchronous
read port (`row_q <= rows[row_read_addr]`) and moves the delayed write port to
its own clocked block. The RAM read register has no reset or initialization.
The stream controller no longer contains array reads. This retains the CE
and pixel pipeline while following the single registered read template used
by `vram_bram.sv`. Simulation checks are recorded in
`scratch/tv_deflicker_inference*.log`.

Quartus must still confirm `rows` maps to M10K and the 30,720-bit register
bank disappears. This repair does not claim a successful synthesis or fit;
no Quartus invocation was made. Check inference in Analysis & Synthesis
before spending time on another full fit. Existing QSF edits are preserved.
