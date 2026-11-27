# IIe card continuation

- Objective: continue the Apple IIe card implementation and qualification on
  `integration-test`. Documentation is in `Apple-IIe-Card/docs`.
- Baseline: `f429711d`; the user ran both revised `upload --driver 5/6
  --transition-render` checks successfully. Each reached service 1, the first
  display ACK and commit, and passed framebuffer and guard comparisons.
- Changes: `tests/iie/tools/monitor_boot.py` checks the service 4 return only
  after ACK and prints assertion values on failure. `check_monitor_upload.py`
  and `monitor_service2.py` add a combined original service 2 continuation
  with supplied slot-selection inputs. `monitor_service3.py` adds the first
  service 3 mismatch return; both driver variants compile, execution pending.
- Tests: user-provided output shows both render passes. Input hashes and wall
  times were not checked. Earlier short-check results are in the card handoff.
- CODE 5 and 6 boot pass after correcting a premature `$FB65` return check: full
  clear, service 4 Y=9, nine banner stores, held service 2 and all framebuffer
  and guard oracles. CODE 6 is user-provided output. CODE 5's runner was changed
  during execution, so its final runner hash does not identify the loaded code.
  A Windows prepare-only attempt failed writing the local host hex (permission
  denied).
- CODE 5 and 6 `--transition-service2` pass original service 2 with flag 0 and
  settings `$A5B6`: A=`$C6` returned through PDS, then service 3 is held with
  A/zero-page `$01`=`$C5` and Y=5. Framebuffer checks pass. Runner, service 2
  test and candidate RTL hashes match the manifest.
- Unresolved: service 3 in the combined transition, unassisted Startup,
  external drive, complete host service and hardware qualification remain open.
  Earlier clear results predate screen-hole and motor suppression.
- Next: collect and diagnose both `--transition-service3` results. The user
  authorized long scripts.

# Live OSD settings

- Objective: require Apply only for machine configuration; preview display
  settings immediately.
- Baseline: `f429711d`; source inspection found aspect ratio, Scale and floppy
  write enable using reset-latched `cfg` alongside memory and monitor sense.
- Changes: `MacLC.sv` reads aspect ratio, Scale and floppy write enable from
  live `status`; pending mask is memory bit 4 and monitor bit 10 only. PRAM
  handling is unchanged. `scripts/osd_check.py` enforces this policy.
- Tests: `wsl python3 scripts/osd_check.py --baseline HEAD` passed both native
  and MAC_TV525 menu variants and saved-option/media compatibility checks.
  `git diff --check` passed. Windows Python aliases and sandboxed WSL could not
  start; WSL check passed with sandbox elevation.
- Unresolved: hardware preview is unverified; no Quartus build run.
- Next: user builds the core and checks live aspect ratio/Scale preview and
  pending indication only for memory/monitor changes.

# Shared Macintosh OSD

- Objective: put everyday media first, keep saved settings compatible, and
  let reset apply any PRAM image selected during the session.
- Baseline: `IIe-refine` at `ca082a48`, with an existing unrelated
  `AGENTS.md` edit. The baseline already deferred manual PRAM selections.
- Changes: `MacLC.sv` groups Floppy, SCSI, CD-ROM and IIe media on the front
  page and keeps their loader indices and format lists. Video and Audio
  have separate pages. Advanced starts with Load ROM, PRAM image, Clear
  PRAM and reset, and Interrupt (NMI). Saved setting bits and value order
  are preserved. `readme.md` uses the current labels.
- PRAM: a replacement invalidates obsolete SD requests and pending saves.
  Only Apply or a machine reset loads a menu selection. Eject cancels it.
  Clear overrides the queued load and writes zeros to the selected image.
  Startup auto-mount, late auto-mount restart and the existing boot and
  read watchdogs remain in place.
- Verified: WSL Icarus compiled the top with unrelated modules unresolved
  and passed `scratch/osd/tb_lc_osd.sv` in the default and a combined
  TV525/IIe overlay variant with MT32-pi, Ethernet and CD-ROM disabled.
  The bench covered startup, pending state, live scaler, deferred Apply,
  eject, in-flight replacement, the ready backstop and clear priority.
  Four static-initialization warnings point to unchanged code.
  `git diff --check` passed. The old `scripts/osd_check.py` has stale menu
  expectations and rejects both the baseline and current layout.
- Next: with a separately authorized hardware build, check menu rendering,
  startup and manual PRAM mounts, and MGL launch using the existing slots.
