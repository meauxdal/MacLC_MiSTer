# LC 480i content instability investigation

Hardware evidence: the electrical frame stays stable, but image contents
become excessively flickery/jittery after Macintosh drawing begins. Initial
solid gray looks perfect. The user explicitly says this is not desktop
dithering. Preserve that distinction: uniform pixels can also hide address,
capture or transport corruption. No anti-flicker filter is enabled or retained.

Further hardware clarification: instability begins with the Happy Mac, with
vertical and horizontal flickering artifacts in diagonal patterns, worsening
as more is drawn. The user directs this investigation toward an RTL/frame
mismatch, excluding Quartus timing as an explanation. No Quartus analysis
is requested or launched; the prepared timing-analysis script was removed.

Investigation started on clean branch `480i`, commit `242c08c`, in the existing
LC checkout. Quadra was not modified. No Quartus process, hardware access,
build, deployment, commit or worktree was started by this investigation.

## Existing hardware reports

`output_files/MacLC.sta.rpt`, dated Oct 8 2026 18:02:38 in the report header,
reports setup failure: native-video receiving clock -18.901 ns, HDMI
-11.663 ns, DDR clock -5.011 ns, CPU clock -3.587 ns. TV receiving clock
setup is +16.762 ns; the design-wide worst hold is +0.106 ns. These are
per-clock summaries, not identified source/destination paths. They do not
establish whether a native/DDR failure is an ordinary synchronous data path,
the intentionally bounded Gray/mailbox crossing, or an unintended constraint.
The positive TV summary does not qualify the whole design.

The report's same-clock Fmax figures are 48.67 MHz native and 113.57 MHz DDR,
above their static 25.18/100 MHz constraints. Thus the negative *receiving-clock*
summaries cannot simply be interpreted as native scanout running too fast.
Detailed paths are needed. The report also warns that `vmode_meta` was not
matched, and that the TV PLL locked-pin exception had an empty source.

`output_files/MacLC_480i_20261008.rbf` exists with SHA256
`418db2c605507b972881232e506332b2ff2dd88eab3d0e4cf025a0fffd60d9a5`.
This does not prove it is the image currently running on the user's MiSTer.
Fitter summary: 76% ALMs, 95% RAM blocks, 5/6 PLLs. No new fit is claimed.

## Expanded simulation coverage

`make tb_tv_v8` now includes the actual dual-clock `vram_bram` and actual
`ariel_ramdac`, rather than only zero VRAM and a palette latency fixture.
The original XOR, zero-VRAM, CE-gap/reset and portrait checks remain.

The new runs program all 256 palette entries through Ariel's CPU register
protocol, hold accesses across multiple latch opportunities, and fill packed
VRAM with independently calculated nonuniform pixels. Both supported
resolutions pass at 1/2/4/8 bpp. Each new run checks 1,536,000 canvas pixels,
14 published images and exact native pixels after startup, with no overflow
or underrun. Borders, first/last pixels and rows are included.

Seven additional runs perform two million CPU-side framebuffer writes each
during native scanout (1/4/8 bpp at both resolutions, 16 bpp at 512x384).
These write framebuffer port A directly; they do not exercise the CPU VRAM
address decoder/packing or the guest's drawing protocol. An independent reference
records complete raw V8 frames before capture. Every displayed sample in
both fields must match one complete recorded image for the entire pair.
This permits native scanout to observe ongoing drawing but rejects transport
corruption or changing frame identity between fields. All seven runs pass with
14 complete source snapshots and zero overflow/underrun. This is functional
simulation, not a model of FPGA metastability, RAM collision uncertainty,
physical setup/hold, or real HPS DDR service latency.

The first nonuniform native frame immediately after reset contains an
unprefetched first row. Steady-frame checks begin after the first native
blanking interval, and TV comparisons wait for later completed publications.
This startup transient is not evidence for continuing content jitter.

Original log: `scratch/tv_jitter_v8.log`; all-depth post-fix log:
`scratch/tv_jitter_all_depths.log`. Re-run from `verilator/` with `make tb_tv_v8`.

The portable frame/canvas, frame-owner and DDR-arbiter regressions also pass,
including contention, dropped pixels, overflow, missed-line black fallback,
mode changes, CE gaps, source loss/reset and whole-pair image identity.
Route verification and `git diff --check` pass. Logs:
`scratch/tv_jitter_transport.log`, `scratch/tv_jitter_routes.log`.
Post-fix transport regression: `scratch/tv_jitter_rtl_regression.log`.

## Reproduced native RTL fault

Extending the nonuniform VRAM test to 512x384 direct 16-bit RGB reproduces a
one-pixel horizontal alignment error. At steady-frame pixel (1,0) the bench
expects RGB 104 but receives 0, the previous pixel's word. The intermediate
`video_data` register was loaded on the same edge that `video_data_d1` sampled
it; direct color consequently lagged the DE/markers by one pixel.

`rtl/maclc_v8_video.sv` now pipelines `pix_word`, the same current-pixel source
used for the palette address, instead of the stale intermediate register.
Pixel extraction and output mode selection also use the synchronized `vmode_v`
already used by word fetch/shift, eliminating the raw CPU-domain mode bypass.
No native counters or raw marker/DE pipeline stages change.

Negative control: `scratch/tv_direct_before.log` fails on the original RTL.
After the fix, `scratch/tv_direct_after.log` checks 1,536,000 canvas pixels,
14 published images, exact native pixels and zero overflow/underrun.
Focused reproduction: `make tb_tv_v8 TV_V8_ARGS=--direct-only`.

This is a proven direct-color alignment fault, not a proven explanation of
the continuing diagonal flicker. It does not affect steady indexed-color
scanout, which passed before this change. The hardware resolution/depth and
a reproduction of the reported instability remain needed to connect a fault
to the observation. Transport tests have not reproduced diagonal corruption.

The capture, FIFO, frame owner, row mapping, deadlines, TV timing, component
conversion and pin routes remain unchanged. No filtering masks the symptom.
