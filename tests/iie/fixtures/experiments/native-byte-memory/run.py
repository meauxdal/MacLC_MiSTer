#!/usr/bin/env python3
"""Bounded byte-mask, ownership, commit and optional patch-composition checks."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess

from prepare import HERE, ROOT, WORK, MACLC, PIN, byte_support, main as prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args, failure=False):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    if failure:
        assert result.returncode and "response 0034 expected 12ab" in result.stdout, result.stdout + result.stderr
    elif result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    prepare()
    modules = [HERE / name for name in ("card_byte_memory_arbiter.sv", "card_byte_native_adapter.sv",
                                      "card_byte_native_port_mux.sv", "tb_native_byte_memory.sv")]
    controller = WORK / "sdram_byte.v"
    scratch = WORK / "apply"
    (scratch / "rtl").mkdir(parents=True, exist_ok=True)
    (scratch / "rtl/sdram.v").write_bytes((MACLC / "rtl/sdram.v").read_bytes())
    for check in (True, False):
        command = ["git", "apply", "--whitespace=nowarn", f"--directory={scratch.relative_to(ROOT).as_posix()}"]
        if check:
            command.append("--check")
        subprocess.run(command + [str(HERE / "native-byte-enable.patch")], cwd=ROOT, check=True,
                       capture_output=True, timeout=10)
    assert (scratch / "rtl/sdram.v").read_bytes() == controller.read_bytes()
    runs = []

    def run_case(name, params=(), source=controller, defines=(), failure=False):
        binary = WORK / (name + ".vvp")
        wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", *defines, "-s", "tb_native_byte_memory",
             *["-Ptb_native_byte_memory." + param for param in params], "-o", linux(binary),
             *map(linux, modules), linux(source)])
        output, errors = wsl(["vvp", linux(binary)], failure=failure)
        assert not errors, errors
        (WORK / (name + ".log")).write_text(output + "\n", encoding="ascii")
        runs.append({"name": name, "expected_failure": failure, "result": output})
        print(output)

    run_case("byte-enabled")
    run_case("high-bit-alias", (f"BASE_WORD={0xD40000}",))
    run_case("default-off", ("ENABLE_MASK=0", "FULL_WORD_ONLY=1"))
    run_case("wrong-byte-enable", ("WRONG_BE=1",), failure=True)
    fair_path = ROOT / "fixtures/experiments/native-admission/run.py"
    assert fair_path.is_file(), "missing expected optional admission transform"
    spec = importlib.util.spec_from_file_location("fair_native_transform", fair_path)
    fair = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fair)
    combined = WORK / "sdram_byte_fair.v"
    combined.write_bytes(byte_support(fair.patched((MACLC / "rtl/sdram.v").read_text(encoding="utf-8"))).encode("utf-8"))
    run_case("composed-fair-enabled", ("NATIVE_FAIR_MODE=1",), combined, ("-DHAS_FAIR_NATIVE",))
    out, err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal", "-DTB_NO_TRISTATE",
                    "--top-module", "tb_native_byte_memory", *map(linux, modules), linux(controller)])
    warnings = [line for line in err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 2 and all("sdram_byte.v:" in line and "WIDTHEXPAND" in line for line in warnings), warnings
    (WORK / "lint.log").write_text(out + "\n" + err + "\n", encoding="ascii")
    assert hashlib.sha256((MACLC / "rtl/sdram.v").read_bytes()).hexdigest() == PIN
    inputs = [*modules, HERE / "prepare.py", Path(__file__), HERE / "native-byte-enable.patch", fair_path, combined]
    result = {"baseline_controller_sha256": PIN, "patch_applies": True, "baseline_unchanged": True,
              "runs": runs, "baseline_lint_warnings": warnings,
              "inputs_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
