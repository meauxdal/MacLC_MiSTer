#!/usr/bin/env python3
"""Bounded allocation audit and isolated real-loader proposal verification."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

from audit import MACLC, PINNED, main as audit, pinned_sources
from prepare_loader import main as prepare

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-memory-allocation"


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args, expected_failure=False):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    if expected_failure:
        assert result.returncode and "loader escaped or aliased reservation" in result.stdout, result.stdout + result.stderr
    elif result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    audit()
    prepare()
    scratch = WORK / "apply"
    (scratch / "rtl").mkdir(parents=True, exist_ok=True)
    (scratch / "rtl/floppy_sd.v").write_bytes((MACLC / "rtl/floppy_sd.v").read_bytes())
    subprocess.run(["git", "apply", "--check", "--whitespace=nowarn",
                    f"--directory={scratch.relative_to(ROOT).as_posix()}", str(HERE / "loader-bounds.patch")],
                   cwd=ROOT, check=True, timeout=10, capture_output=True)
    subprocess.run(["git", "apply", "--whitespace=nowarn",
                    f"--directory={scratch.relative_to(ROOT).as_posix()}", str(HERE / "loader-bounds.patch")],
                   cwd=ROOT, check=True, timeout=10, capture_output=True)
    assert (scratch / "rtl/floppy_sd.v").read_bytes() == (WORK / "floppy_sd_bounded.v").read_bytes()
    bench, source = HERE / "tb_loader_bounds.sv", WORK / "floppy_sd_bounded.v"
    runs = []
    for words in (512, 1048576, 0, 8388609):
        binary = WORK / f"loader-{words}.vvp"
        wsl(["iverilog", "-g2012", "-s", "tb_loader_bounds", f"-Ptb_loader_bounds.TEST_WORDS={words}",
             "-o", linux(binary), linux(bench), linux(source)])
        output, errors = wsl(["vvp", linux(binary)])
        assert not errors, errors
        (WORK / f"simulation-{words}.log").write_text(output + "\n", encoding="ascii")
        runs.append({"region_words": words, "result": output})
        print(output)
    # Disable only the after-header size check; a 1025-byte raw image must escape.
    mutant = source.read_bytes().decode("utf-8").replace(
        "if (sd_lba == 0 && (dc42 ?", "if (1'b0 && (dc42 ?")
    mutant_path = WORK / "floppy_sd_unsafe.v"
    mutant_path.write_bytes(mutant.encode("utf-8"))
    wsl(["iverilog", "-g2012", "-s", "tb_loader_bounds", "-o", linux(WORK / "unsafe.vvp"),
         linux(bench), linux(mutant_path)])
    negative, _ = wsl(["vvp", linux(WORK / "unsafe.vvp")], expected_failure=True)
    (WORK / "negative-control.log").write_text(negative + "\n", encoding="ascii")
    out, err = wsl(["verilator", "--lint-only", "--timing", "--top-module", "tb_loader_bounds",
                    linux(bench), linux(source)])
    (WORK / "lint.log").write_text(out + "\n" + err + "\n", encoding="ascii")
    assert "%Warning" not in out + err and "%Error" not in out + err
    pinned_sources()
    inputs = [HERE / "audit.py", HERE / "prepare_loader.py", Path(__file__), bench, source,
              HERE / "loader-bounds.patch"]
    result = {"mode": "isolated proposal only; not applied to MacLC", "runs": runs,
              "negative_control": negative, "lint_warnings": 0, "patch_applies": True,
              "baseline_unchanged": True, "source_sha256": PINNED,
              "inputs_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "loader-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print("PASS after-header bounds negative control, zero-warning lint and unchanged MacLC")


if __name__ == "__main__":
    main()
