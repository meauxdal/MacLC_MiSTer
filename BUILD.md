# Building the MacLC core

There are two ways to build the FPGA core: the Quartus GUI, or the scripted CLI flow
in `scripts/`. This document covers the **CLI flow** — repeatable, headless-friendly,
and core-agnostic (the same `build_only.sh` works in other MiSTer core repos with no
edits). For the GUI, just open `MacLC.qpf` in Quartus and run a full compilation.

The build **never touches the MiSTer** — deploying is a separate step (see
[Deploy](#deploy-optional-separate-step)).

## Optional 480i support

480i support is enabled by this assignment in `MacLC.qsf`:

```tcl
set_global_assignment -name VERILOG_MACRO "MAC_TV525_DIAG=1"
```

Comment out or remove the assignment before building to omit the 480i hardware
and its CRT De-flicker OSD control. Do not set the macro to `0`:
the RTL uses `ifdef`, which checks whether it is defined, regardless of its value.
In the Quartus GUI, remove the macro from the project's Verilog HDL macro settings.

With support included, both analog and scaled HDMI use 480i from startup.
CRT De-flicker selects Strong, Mild or Off. There is no runtime Native/480i toggle.
Remove the macro and rebuild for native progressive output.

The standard MiSTer framework supplies OSD, RGB/component conversion and sync.
For CRT output use unscaled analog video; select component or composite sync in
MiSTer configuration as required by the display. HDMI direct video carries 480i;
use scaled HDMI for a progressive HDMI display.

### Offline OSD check

Run `python scripts/osd_check.py` to check both expanded menu variants, root and
submenu selection, flat mode, scrolling, media slots and status ranges without
building hardware. `--baseline c9e0b0d` also reproduces the old invisible-version
row offset and checks that option values and hardware logic remain unchanged.
The check models Main's drawing and selection separately; it does not execute
Main or replace a hardware OSD check. Its source revision references and optional
`--main-source-dir` cross-check are documented in the script.

## Prerequisites

- **Intel Quartus Prime 17.0.2 Lite Edition** installed. Typical `bin` locations:
  - Linux: `/home/<you>/intelFPGA_lite/17.0/quartus/bin` (or `/opt/intelFPGA_lite/17.0/quartus/bin`)
  - Windows (git-bash): `/c/intelFPGA_lite/17.0/quartus/bin64`
  - macOS: `/Applications/intelFPGA_lite/17.0/quartus/bin`
- **Bash** — Linux, macOS, or Windows git-bash.

## First-time setup (once per machine)

The scripts read machine/core settings from `scripts/local.env`, which is **gitignored**
(it holds your Quartus path and — for deploy — the MiSTer host/ssh key). Generate it from
the committed template:

```bash
bash scripts/setup_env.sh          # copies scripts/local.env.sample -> scripts/local.env
```

Then edit `scripts/local.env` and set at least your Quartus bin dir:

```
QUARTUS_BIN=/home/you/intelFPGA_lite/17.0/quartus/bin
```

That is all that is required **to build**. (Deploy additionally needs `MISTER_HOST` and
`MISTER_SSH_KEY` — see the comments in `scripts/local.env.sample`.)

## Build

```bash
bash scripts/build_only.sh          # full compile -> output_files/MacLC.rbf, then a status summary
```

A full compile takes roughly **20 minutes**. Run it in a terminal you can leave open, or
as a background task.

| command | what it does |
|---|---|
| `bash scripts/build_only.sh` | full compile → `.sof` + `.rbf` |
| `bash scripts/build_only.sh --check` | fast (~3–4 min) Analysis & Synthesis only; **no `.rbf`** — a syntax / multi-driver sanity check |
| `bash scripts/build_only.sh --no-wait` | don't wait for another in-progress Quartus (see [Multiple builds](#running-multiple-builds-on-one-host)) |
| `bash scripts/build_only.sh -h` | help |

### Reading the status summary

At the end `build_only.sh` prints a summary, for example:

```
BUILD STATUS  (MacLC, 22m48s)
  Analysis & Synthesis   Analysis & Synthesis Status : Successful - ...
  Fitter                 Fitter Status : Successful - ...
  Timing (STA)           met — worst slack +0.246 ns
  Artifact               output_files/MacLC.rbf  (4368544 bytes, ...)
  Quartus flow           exit=0
```

- **Timing (STA)** must read `met` (positive worst-case slack). `VIOLATED` means timing
  was not met and the `.rbf` should not be trusted for hardware.
- **Artifact** must be present. The script's exit code is nonzero on any failure.
- The full Quartus log is written to `output_files/build_<timestamp>.log`.

## Deploy (optional, separate step)

Building produces `output_files/MacLC.rbf` but does not push it anywhere. To push the
build to a MiSTer, reboot it, and select the core over the OSD:

```bash
# requires MISTER_HOST + MISTER_SSH_KEY in scripts/local.env
bash scripts/deploy_screenshot.sh
```

See `tools/misterdeploy/README.md` for the reusable launcher this wraps, including NVRAM
save-image seeding (the `SEED_*` settings in `local.env`).

## Running multiple builds on one host

- **The same core twice at once — don't.** Both compiles share `db/`, `incremental_db/`,
  and `output_files/`, so they would corrupt each other. `build_only.sh` prevents this:
  the second invocation waits (30 s poll) until the first Quartus finishes.
- **Two *different* cores** (e.g. MacLC and LBMacTwo, in separate repo directories):
  Quartus *can* build them in parallel — they share no working state, and Lite has no
  concurrency license lock. **But** `build_only.sh`'s wait-gate is host-global (it matches
  *any* running `quartus_*` process), so by default the second build **waits** and they run
  sequentially. To force them to run at the same time, launch the second with `--no-wait`.
  Note that two full compiles contend for RAM/CPU, so each becomes slower — running them
  sequentially is often nearly as fast and is safer.

## Portability to other cores

`build_only.sh` needs **no per-core edits**. It auto-detects the Quartus revision from the
single `*.qsf` in the repo root (override with `QUARTUS_REVISION` for multi-revision
projects) and derives the `.rbf` name from it. To reuse this toolchain in another MiSTer
core repo, copy `scripts/build_only.sh` (and, for the env template + generator,
`scripts/setup_env.sh` and `scripts/local.env.sample`) into that repo, run
`bash scripts/setup_env.sh`, set `QUARTUS_BIN`, and build.
