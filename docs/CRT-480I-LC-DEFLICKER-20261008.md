# CRT de-flicker experiment

October 9 HDMI follow-up: hardware reports fragmented HDMI text and serrated
edges, unaffected by changing de-flicker. Earlier statements that HDMI is
unchanged describe intended routing, not hardware qualification. The full
native-path audit and actual ASCAL/TV-contention regression are recorded in
[HDMI isolation investigation](HDMI-480I-ISOLATION-20261009.md). Authorized
STA subsequently exposed missing native/HDMI clock exceptions past the
dedicated selectors and large inserted hold delays on HDMI output paths.
`MacLC.sdc` repairs those exceptions while retaining FIFO Gray budgets. A
new fit and hardware check are still required to establish the picture fix;
broad OSD cleanup is deferred.

## Hardware result and optional output follow-up

The user verified on hardware that Strong resolves the stationary curved,
rapidly flickering desktop moire bands and that 480i looks good. A sync defect
is not established. The sections below record the original experiment and
RAM inference repair; the current menu/defaults supersede the original Off
default.

`O3,Analog Output,Native,480i` uses previously unused status bit 3. Zero selects
the existing analog route, including its native clock/scaler choice, sync,
component conversion, low DAC bits and normal VGA OSD. This retains regular
24 kHz output with the 512x384 monitor selection. It does not force a monitor
mode or change the guest raster. Selecting 480i switches only the analog pin
and clock routes to the existing TV path. HDMI is unchanged. Both paths and
their OSD command receivers keep running, so returning to 480i does not reset
its raster, DDR store or complete-image owner. OSD_STATUS follows the selected
analog OSD. A display may reacquire sync when changing output rates.

`O12,CRT De-flicker,Strong,Mild,Off` retains bits 2:1 and maps status values
0/1/2/3 to filter modes Strong/Mild/Off/Strong. The synchronizer initializes
to Strong. No host status write or new default-setting protocol is introduced;
the first menu entry supplies the zero-status default. Existing saved O12
values use the new order (a saved value 0 now means Strong and 2 means Off).
The filter still latches once per complete source image. The repaired RAM
template in `rtl/tv_deflicker.sv` is unchanged.

Verification: route checks compare every native RGB/sync/low-bit expression
against HEAD, check clock selection and both OSD status routes, and preserve
normal/historical macro profiles and HDMI pin assignments. `tb_tv_deflicker`
passes 8,825,856 exact pixels; `tb_tv525_platform` passes 5,405,400 sync/DE
samples; `tb_tv_frame TV_FRAME_FILTER=2` passes all geometries, both fields,
healthy and injected-fault cases; `tb_tv_frame_owner` passes complete-pair
ownership and rejection checks. Logs are `scratch/tv_optional_regression.log`
and `scratch/tv_optional_owner.log`. No Quartus build or deployment was run;
the selector, restored VGA OSD resource use and fitted timing still need an
authorized build and hardware toggle check. No commit or publication was made.

Necessary conditional integration hooks in `sys_top.v` and `emu_ports.vh`
are within the explicit optional-output request. Broad OSD cleanup is deferred
to step two, which must review status allocation, syntax, defaults and the
Main/core contract before an upstream contribution.

### October 9 clock-selector correction

The user's build failed Analysis & Synthesis with Error 15836: the initial
three-PLL `vga_clk_sw` placed `hdmi_clk_out` on `inclk[1]`. Cyclone V reserves
inputs 0/1 for clock pins and 2/3 for PLL outputs; a single dedicated selector
cannot dynamically select all three PLL sources. The original route check
accepted the wiring but did not enforce this hardware restriction.

The correction restores the original native/HDMI dedicated selector with
both PLLs on inputs 2/3. A fabric mux selects that result or `clk_tv525` only
for the existing `vgaclk_ddr` forwarded clock output on LED_USER. It clocks
no internal video, memory or core pipeline. Both analog paths keep running.
Switching rates may truncate an output clock pulse during display sync
reacquisition; this is not a glitch-free clock-switching claim. The portable
TV timing and pixel RTL, pin data selection and OSD paths are unchanged.
Route checks now reject PLLs in the clock-pin input positions and verify the
selected forwarding clock has no other consumers. All route checks pass.
Quartus was not run; synthesis, routing and forwarded-clock timing still
require the user's next build. The prior simulation results remain applicable
to the unchanged picture pipeline.

Hardware restriction reference: [Cyclone V Device Handbook, clock control
blocks](https://www.intel.com/programmable/technical-pdfs/683375.pdf).

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
