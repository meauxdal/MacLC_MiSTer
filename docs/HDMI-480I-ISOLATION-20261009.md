# HDMI isolation investigation, October 9

The starting checkout is clean `480i` at `6536ff8` (interlace toggle), which
includes the optional-output changes described as uncommitted in the handoff.
The photograph shows fragmented text and serrated vertical edges. It was
inspected and preserved as `scratch/hdmi-fragmented-20261009.png`. It does not
establish a filter, sync, capture, transport, or timing cause. The user reports
that CRT de-flicker changes do not affect the broken HDMI image. The new
optional-output build was still running; its Native-output result is pending.

Production RTL, QSF, QIP and build stamp are unchanged. The focused STA test
was explicitly authorized and run against the existing fit. `MacLC.sdc` now
repairs the proven missing native/HDMI clock exceptions described below. No
map, fit, full compilation, deployment, commit or publication was made. Broad
OSD cleanup remains deferred. The resulting hardware picture still requires
a new fit and hardware qualification; no successful hardware fix is claimed.

## Full native path audit

The native clock and CE, raw V8 RGB/DE/sync, native field flag (`VGA_F1=0`),
scanlines (`VGA_SL=0`), HDMI freeze/blackout/bob controls, framework scanline
input, HDMI scaler input and controls, HPS measurement bus, shadowmask, HDMI
OSD, direct-video source, HDMI clock selector and registered output path
retain the progressive route. Filter outputs feed the TV capture path. The
analog selector affects the DAC/pin/forwarded-clock and OSD-status routes.
TV and ASCAL share the DDR port through `tv_ddr_arbiter`; unchanged HDMI pin
assignments alone cannot verify that integration.

`check_tv_frame_routes.py` now compares these complete native paths, including
ASCAL's non-memory ports. Its baseline is pinned to `70229a3`, before the
optional selector. Using HEAD stopped being a valid oracle when the optional
change was committed: it compared a selected TV expression to an entire
optional-output ternary and failed on VGA_VS. Existing normal, historical,
TV-only and TV+HDMI profile checks also pass.

## Actual ASCAL under TV traffic

The new `verilator/check_hdmi_ascal.py` translates the repository's actual
`sys/ascal.vhd` with GHDL and simulates it with the production TV arbiter using
Verilator. ASCAL parameters match the LC framework's 128-bit/28-bit DDR port,
base 0x20000000, 8 MiB slots, FRAC=8 and PALETTE2=false. The input is a static,
nonuniform RGB gradient at each supported native geometry. The comparison
uses direct DDR service as a reference and continuous 160-beat reads from
the reserved TV region as contention. DDR accepts one response beat per
memory clock and occasionally stalls commands. Both pictures run six frames;
the last three compare complete progressive RGB/DE/HS/VS streams.

| Geometry | Equal captured write beats | Equal output samples | Active picture pixels | TV read bursts |
| --- | ---: | ---: | ---: | ---: |
| 640x480 | 307,184 | 1,260,000 | 921,600 | 57,925 |
| 512x384 | 184,336 | 781,440 | 589,824 | 36,003 |

Image-relative write addresses and every byte match; buffer slot identity may
legally differ. Coverage rejects an empty or predominantly black comparison.
Both source/output domains use 25 MHz functional clocks against 100 MHz DDR,
including the 512x384 case as a deliberate higher-rate stress. This is not a
model of physical PLL clocks, timing, metastability, FPGA RAM collisions,
arbitrary HPS memory latency, actual guest VRAM writes or Main's live HDMI
configuration. Other existing benches cover V8/VRAM/palette and TV ownership.

An initial 128x64 synthetic raster showed a first-burst word difference under
stalls. It did not reproduce at either supported LC geometry and has not been
connected to the hardware report. It was not used to justify an RTL change.

Reproduce in an environment with GHDL and Verilator, from `verilator/`:

```sh
python3 check_tv_frame_routes.py
python3 check_hdmi_ascal.py
python3 check_hdmi_ascal.py --negative-control
```

Generated sources, build logs and results stay in
`scratch/hdmi_ascal_regression/`. The negative control rotates each scaler
receive word by one byte in a scratch copy of the arbiter; the real RTL is
unchanged. It must fail the exact progressive output comparison.
The negative control passes: the deliberately corrupted stream is rejected
with `progressive HDMI pixel/sync mismatch`.

## Remaining hardware evidence

The user confirms the HDMI OSD has always been correct, analog picture is
correct, and resolution, analog-output type and de-flicker have no effect on
the broken HDMI picture. This points to the scaled-picture path ahead of the
HDMI OSD; it does not prove a particular RTL or physical timing fault. The
HDMI OSD is composed after ASCAL and shadowmask, so it can be clean while
upstream picture data is bad.

The existing local TimeQuest report dated October 9 00:28:22 reports the
user's -0.525 ns figure as **hold** in the 65.01 MHz core/SDRAM domain. It also
reports HDMI setup -11.941 ns and HDMI same-clock Fmax 75.64 MHz against the
static 148.54 MHz HDMI clock. These are separate results. DDR same-clock
Fmax is 112.18 MHz against 100 MHz; native-video Fmax is 47.27 MHz against the
static 25.18 MHz clock. The report's Fmax panel explicitly excludes paths
between different clocks. The report therefore contains evidence of an
HDMI same-clock timing limitation as well as asynchronous-clock setup
violations, but no detailed start/end nodes. The failing HDMI nodes may be
picture arithmetic, controls, or another path; causality is unestablished.

## Proven constraint fault and correction

With explicit authorization for this diagnostic test, `quartus_sta` loaded
the existing fit and extracted full paths. The -0.525 ns hold path is
`sdram_dldin_q[3]` to `sdram|din_q[3]`, from 32.5 to 65 MHz. A second SDRAM
input hold path is -0.282 ns. They are real reported failures, distinct from
the HDMI output failure.

The HDMI same-clock worst path is `d[6]` to `hdmi_out_d[6]`, -6.489 ns setup,
with no combinational logic and 13.307 ns interconnect delay. The fitter's
hold-repair details list 9.190 ns added to that connection and roughly
9–10 ns on many HDMI output-pipeline connections. The worst all-clock HDMI
path is the same connection timed from native PLL to HDMI PLL, -11.941 ns.

The buffered-TV SDC replaced the ordinary native asynchronous clock group
with exceptions derived from `get_fanouts -no_logic` of the native PLL.
Actual TimeQuest collection auditing shows 15,481 keepers in that fanout but
neither `d[6]` nor `hdmi_out_d[6]` is present. The walk stops at dedicated
native/HDMI clock selectors. TimeQuest nevertheless propagates both clocks
to their downstream registers, leaving the mutually incompatible native/
HDMI transfers constrained. The fitter added large hold delays to these
connections and the real HDMI same-clock paths then fail setup. This is a
proven exception-coverage defect and fitted-path failure; the exact hardware
symptom still needs a corrected fit to establish causality.

`MacLC.sdc` restores just the two native-to-HDMI and HDMI-to-native clock
relationship cuts that the normal profile already had. It does not add a
native/DDR clock-group cut or suppress HDMI same-clock timing. Actual STA on
the existing fit confirms:

| Check after correction | Result |
| --- | --- |
| Native to HDMI and HDMI to native | No timed paths, as intended |
| Capture FIFO write Gray bus | All 11 bits timed under the 8 ns max-delay; worst slack +4.029 ns |
| Capture FIFO read Gray bus | All 11 bits timed under the 8 ns max-delay; worst slack +4.800 ns |
| DDR same-clock setup | +1.086 ns |
| Native same-clock setup | +18.549 ns |
| HDMI same-clock setup, existing fit | Still -6.489 ns: physical hold delays have not been removed |

`verilator/check_tv_sdc.py` now models output registers beyond the selector
and requires both clock exceptions. Its negative control removes those cuts
and must fail even with all Gray endpoints present. All mock profiles and
missing-endpoint rejection checks pass. These mocks supplement the actual
TimeQuest endpoint checks; they do not replace physical verification.

Evidence is in `scratch/hdmi_timing_paths.log`,
`scratch/hdmi_timing_paths_audit.log`, `scratch/hdmi_timing_paths_fifo.log`,
`scratch/hdmi_same_clock_setup.rpt`, `scratch/hdmi_core65_hold.rpt`, and
`scratch/hdmi_capture_gray_{write,read}.rpt`. The original fitter hold-delay
details remain in `output_files/MacLC.fit.rpt`.

The current authorization covers STA diagnostics only. A new fit is required
to remove the old inserted hold delays and verify actual HDMI setup/hold,
the separate SDRAM hold failures, retained FIFO max-delay/skew budgets and
hardware behavior. No additional Quartus build or hardware load is authorized.

No sync defect or hardware fix is claimed. Narrow framework corrections
remain authorized if a fault is established, but an unsupported picture-
changing patch would confound this comparison.
