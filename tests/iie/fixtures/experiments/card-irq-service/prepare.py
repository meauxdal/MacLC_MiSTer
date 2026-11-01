#!/usr/bin/env python3
"""Compile a separate live-service executable using the isolated IRQ variant."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-irq-service"
WRAPPER_PINS = {
    "fixtures/experiments/card-platform/card_platform.sv": "64002ab0ccb5fb08634dae5c7c41bdc9b8f7df20b3804a44ac8d2f0bf3d49d44",
    "fixtures/experiments/card-pds-system-harness/card_pds_candidate.sv": "30f823ebbac4f4125e4bfa534edf85190962df1c80b010a32911443c21be5ee3",
    "fixtures/experiments/card-rtl-service/card_rtl_service.sv": "d6f315a949e07cf0dc4dca7abfd6f3c435f0b588538cdab770cad01eb0942013",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    baseline_vvp = ROOT / "local/experiments/card-rtl-service/service.vvp"
    baseline_sha = sha(baseline_vvp)
    variant_generator = ROOT / "fixtures/experiments/card-irq-system/prepare.py"
    spec = importlib.util.spec_from_file_location("irq_variant_prepare", variant_generator)
    variant = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(variant)
    cpu, host, card = variant.generate(WORK)
    substitutes = {
        (ROOT / "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv").resolve(): cpu,
        (ROOT / "fixtures/experiments/card-host-rtl/card_host_registers.sv").resolve(): host,
        (ROOT / "fixtures/experiments/card-system-harness/card_candidate.sv").resolve(): card,
    }
    for name, expected in WRAPPER_PINS.items():
        assert sha(ROOT / name) == expected, name
    rewrites = {
        "fixtures/experiments/card-platform/card_platform.sv":
            {"module card_platform #": "module card_irq_platform #", "    card_pds_candidate card (": "    card_irq_pds_candidate card ("},
        "fixtures/experiments/card-pds-system-harness/card_pds_candidate.sv":
            {"module card_pds_candidate (": "module card_irq_pds_candidate (", "    card_candidate card (": "    card_irq_candidate card ("},
        "fixtures/experiments/card-rtl-service/card_rtl_service.sv":
            {"    card_platform dut (": "    card_irq_platform dut ("},
    }
    for source, replacements in rewrites.items():
        path = ROOT / source
        text = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            assert text.count(old) == 1, old
            text = text.replace(old, new, 1)
        output = WORK / path.name
        output.write_text(text, encoding="ascii", newline="\n")
        substitutes[path.resolve()] = output
    qip = ROOT / "fixtures/experiments/card-platform/card_platform.qip"
    names = re.findall(r"\[file join \$::quartus\(qip_path\) ([^\]]+)\]", qip.read_text())
    assert len(names) == 12
    original_closure = [(qip.parent / name).resolve() for name in names]
    assert len(set(original_closure)) == 12
    closure = [substitutes.get(path, path) for path in original_closure]
    original_service = ROOT / "fixtures/experiments/card-rtl-service/card_rtl_service.sv"
    service = substitutes[original_service.resolve()]
    controller = ROOT.parents[1] / "rtl/sdram.v"
    paths = [service, *closure, controller]
    for path in paths:
        assert path.is_file(), f"missing expected source: {path}"
    executable = WORK / "service.vvp"
    wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "card_rtl_service", "-o", linux(executable), *map(linux, paths)])
    lint_out, lint_err = wsl(["verilator", "--lint-only", "--timing", "-Wno-fatal", "-DTB_NO_TRISTATE",
                              "--top-module", "card_rtl_service", *map(linux, paths)])
    warnings = [line for line in lint_err.splitlines() if line.startswith("%Warning")]
    assert len(warnings) == 2 and all("/rtl/sdram.v:" in line and "WIDTHEXPAND" in line for line in warnings), warnings
    (WORK / "lint.log").write_text(lint_out + "\n" + lint_err + "\n", encoding="utf-8")
    assert sha(baseline_vvp) == baseline_sha, "baseline executable changed"
    inputs = [Path(__file__), variant_generator, qip, original_service, *original_closure, controller]
    result = {
        "scope": "isolated IRQ variant of blocking PDS/two-clock/native-SDRAM service",
        "executable": executable.relative_to(ROOT).as_posix(), "success_boundary": "203A",
        "baseline_executable_sha256": baseline_sha, "baseline_executable_preserved": True,
        "baseline_lint_warnings": warnings,
        "generated_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in [*substitutes.values(), executable]},
        "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"): sha(p)
                          for p in inputs},
    }
    (HERE / "prepare-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(executable)


if __name__ == "__main__":
    main()
