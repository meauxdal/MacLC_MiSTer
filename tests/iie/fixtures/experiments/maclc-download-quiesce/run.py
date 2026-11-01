#!/usr/bin/env python3
"""Bounded pinned HPS protocol and actual SDRAM download-port checks."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

import hps_prepare
from prepare import HERE, ROOT, WORK, MACLC, PINS, prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args, failure=None):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    output = result.stdout.strip()
    if failure:
        assert result.returncode and failure in output, output + result.stderr
    elif result.returncode:
        raise RuntimeError(output + result.stderr)
    return output, result.stderr.strip()


def compile_bench(name, top, sources, options=()):
    binary = WORK / (name + ".vvp")
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", *options, "-s", top,
         "-o", linux(binary), *map(linux, sources)])
    return binary


def main():
    prepare()
    hps_source = hps_prepare.prepare()
    runs = []

    def record(name, binary, args=(), failure=None):
        output, errors = wsl(["vvp", linux(binary), *args], failure=failure)
        assert not errors, errors
        if not failure:
            assert "PASS" in output, output
        print(output, flush=True)
        (WORK / (name + ".log")).write_text(output + "\n", encoding="ascii")
        runs.append({"name": name, "expected_failure": failure, "result": output})

    hps_sources = [HERE / "tb_hps_protocol.sv", hps_source]
    binary = compile_bench("hps", "tb_hps_protocol", hps_sources)
    record("hps", binary)
    binary = compile_bench("drop-on-stop", "tb_hps_protocol", hps_sources,
                           ["-Ptb_hps_protocol.DROP_ON_STOP=1"])
    record("drop-on-stop", binary, failure="stop lost offered word")
    ingress_sources = [HERE / "tb_hps_ingress.sv", hps_source, WORK / "maclc_download.sv"]
    binary = compile_bench("hps-ingress", "tb_hps_ingress", ingress_sources)
    record("hps-ingress", binary)
    sources = [HERE / "tb_download.sv", WORK / "maclc_download.sv", WORK / "sdram.v",
               HERE.parent / "card-quiesce/card_warm_reset.sv"]
    binary = compile_bench("download", "tb_download", sources)
    for phase in (2, 7):
        record(f"download-phase-{phase}", binary, [f"+PHASE={phase}"])

    # The assertions exercised by each mutation are recorded in the manifest.
    negatives = [
        ("rom-override", "UNSAFE_ROM_OVERRIDE", "late ROM overrode locked owner"),
        ("wait-request", "UNSAFE_WAIT_REQUEST", "backpressure flag became ROM request"),
        ("release-ack", "UNSAFE_RELEASE_ACK", "next accepted word consumed stale ACK"),
        ("early-init", "UNSAFE_EARLY_INIT", "immediate init discarded posted write"),
    ]
    for name, define, marker in negatives:
        binary = compile_bench(name, "tb_download", sources, ["-D" + define])
        record(name, binary, failure=marker)

    out, err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal",
                    "-Wno-PINMISSING", "-DTB_NO_TRISTATE", "--top-module", "tb_download",
                    *map(linux, sources)])
    warnings = [line for line in err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 2 and all("sdram.v" in w and "WIDTHEXPAND" in w for w in warnings), err
    (WORK / "lint.log").write_text(out + "\n" + err, encoding="ascii")
    for name, pin in {**PINS, **hps_prepare.PINS}.items():
        assert hashlib.sha256((MACLC / name).read_bytes()).hexdigest() == pin, name
    inputs = [*sources, *hps_sources, *ingress_sources, HERE / "prepare.py", HERE / "hps_prepare.py", Path(__file__),
              HERE.parent / "card-quiesce/prepare.py", *(MACLC / name for name in {**PINS, **hps_prepare.PINS})]
    (HERE / "results.json").write_text(json.dumps({
        "scope": "pinned HPS framing/handshake; extracted and transformed MacLC ingress/mux/register; actual SDRAM controller",
        "hps_fence": "harness-only contract; existing HPS IO has no admission acknowledgment",
        "loader_committer": "word-level producer models; full engines and ownership excluded",
        "baseline_sources_unchanged": True, "sys_period_ns": 20, "mem_period_ns": 10,
        "runs": runs, "lint_warnings": warnings,
        "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"):
                          hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
