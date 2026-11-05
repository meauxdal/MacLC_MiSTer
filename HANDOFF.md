# IIe card continuation

- Objective: continue the Apple IIe card implementation and qualification on
  `integration-test`. Documentation is in `Apple-IIe-Card/docs`.
- Baseline: `f429711d`; the user ran both revised `upload --driver 5/6
  --transition-render` checks successfully. Each reached service 1, the first
  display ACK and commit, and passed framebuffer and guard comparisons.
- Changes: `tests/iie/tools/monitor_boot.py` checks the service 4 return only
  after ACK and prints assertion values on failure. `MacLC.qsf` was already
  marked modified when the results arrived; preserve it.
- Tests: user-provided output shows both render passes. Input hashes and wall
  times were not checked. Earlier short-check results are in the card handoff.
- CODE 6 boot passes after correcting a premature `$FB65` return check: full
  clear, service 4 Y=9, nine banner stores, held service 2 and all framebuffer
  and guard oracles. User output supplied; input hashes and wall time unchecked.
  A Windows prepare-only attempt failed writing the local host hex (permission
  denied). CODE 5 boot result is not provided.
- Unresolved: CODE 5 boot, unassisted Startup,
  external drive, complete host service and hardware qualification remain open.
  Earlier clear results predate screen-hole and motor suppression.
- Next: run `upload --driver 5 --transition-boot`. Repository instructions
  require the user to run long scripts.

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
