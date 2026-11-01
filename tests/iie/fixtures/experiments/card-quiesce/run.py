#!/usr/bin/env python3
"""Actual-controller drain-first reset and immediate-init cancellation control."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess

from prepare import HERE, ROOT, WORK, MACLC, PIN, quiesce_support, main as prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    prepare()
    common = [ROOT / "fixtures/experiments/card-host-rtl/card_host_registers.sv",
              ROOT / "fixtures/experiments/memory-harness/card_memory_arbiter.sv",
              ROOT / "fixtures/experiments/card-memory-cdc/card_memory_cdc.sv",
              ROOT / "fixtures/experiments/native-memory-harness/card_native_memory_adapter.sv",
              ROOT / "fixtures/experiments/native-memory-harness/card_native_port_mux.sv"]
    bench = HERE / "tb_card_quiesce.sv"
    sequencer = HERE / "card_warm_reset.sv"
    controller = WORK / "sdram_quiesce.v"
    scratch = WORK / "apply"
    (scratch / "rtl").mkdir(parents=True, exist_ok=True)
    (scratch / "rtl/sdram.v").write_bytes((MACLC / "rtl/sdram.v").read_bytes())
    for check in (True, False):
        command = ["git", "apply", "--whitespace=nowarn", f"--directory={scratch.relative_to(ROOT).as_posix()}"]
        if check:
            command.append("--check")
        subprocess.run(command + [str(HERE / "controller-quiesce.patch")], cwd=ROOT, check=True,
                       capture_output=True, timeout=10)
    assert (scratch / "rtl/sdram.v").read_bytes() == controller.read_bytes()
    runs = []

    def simulate(name, source=controller, params=(), defines=()):
        binary = WORK / (name + ".vvp")
        wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", *defines, "-s", "tb_card_quiesce",
             *["-Ptb_card_quiesce." + param for param in params], "-o", linux(binary),
             *map(linux, [sequencer, bench, *common, source])])
        output, errors = wsl(["vvp", linux(binary)])
        assert not errors, errors
        (WORK / (name + ".log")).write_text(output + "\n", encoding="ascii")
        runs.append({"name": name, "result": output})
        print(output)

    simulate("coordinated")
    simulate("immediate-init-negative", params=("NEGATIVE_CONTROL=1",))
    fair_path = ROOT / "fixtures/experiments/native-admission/run.py"
    byte_path = ROOT / "fixtures/experiments/native-byte-memory/prepare.py"
    fair = load("fair_reset_transform", fair_path)
    byte = load("byte_reset_transform", byte_path)
    combined = WORK / "sdram_all_options.v"
    combined.write_bytes(quiesce_support(byte.byte_support(fair.patched(
        (MACLC / "rtl/sdram.v").read_text(encoding="utf-8")))).encode("utf-8"))
    simulate("composed-options", source=combined, defines=("-DHAS_OPT_NATIVE",))
    # New unconnected quiesce input is inert with the default parameter zero.
    baseline_bench = ROOT / "fixtures/experiments/native-memory-harness/tb_native_memory.sv"
    baseline_sources = [baseline_bench, common[1], common[3], controller]
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "tb_native_memory", "-o",
         linux(WORK / "default-off.vvp"), *map(linux, baseline_sources)])
    output, errors = wsl(["vvp", linux(WORK / "default-off.vvp")])
    assert not errors and "PASS native-memory accepted=44 completed=44 backend=47" in output, output + errors
    runs.append({"name": "default-off-existing-native-regression", "result": output})
    print(output)
    out, err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal", "-DTB_NO_TRISTATE",
                    "--top-module", "tb_card_quiesce", *map(linux, [sequencer, bench, *common, controller])])
    warnings = [line for line in err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 2 and all("sdram_quiesce.v:" in line and "WIDTHEXPAND" in line for line in warnings), warnings
    (WORK / "lint.log").write_text(out + "\n" + err + "\n", encoding="ascii")
    assert hashlib.sha256((MACLC / "rtl/sdram.v").read_bytes()).hexdigest() == PIN
    inputs = [sequencer, bench, *common, baseline_bench, HERE / "prepare.py", Path(__file__),
              HERE / "controller-quiesce.patch", fair_path, byte_path, combined]
    (HERE / "results.json").write_text(json.dumps({
        "scope": "actual controller and host/memory components; manual CPU/source stop hooks",
        "baseline_sha256": PIN, "baseline_unchanged": True, "patch_applies": True,
        "runs": runs, "baseline_lint_warnings": warnings,
        "inputs_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"):
                          hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
