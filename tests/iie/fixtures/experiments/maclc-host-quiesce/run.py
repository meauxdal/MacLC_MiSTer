#!/usr/bin/env python3
"""Bounded actual TG68K wrapper/kernel pause and resume checks."""
import hashlib
import json
import shlex
import subprocess
from prepare import HERE, ROOT, MACLC, WORK, PINS, main as prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def main():
    prepare()
    sources = [HERE / "tb_host_stop.sv", WORK / "tg68k.v",
               MACLC / "rtl/tg68k/TG68KdotC_Kernel.v"]
    binary = WORK / "host.vvp"
    runs = []
    baseline_memory = None
    for state, vpa, enable, held, berr in [(-1, 0, 0, 0, 0), (-1, 0, 1, 0, 0),
            (-1, 0, 1, 0, 1), (5, 0, 1, 0, 0),
            *[(s, v, 1, h, 0) for s in range(0, 5) for v, h in ((0, 0), (1, 0), (0, 1))],
            *[(s, 0, 1, 0, 1) for s in range(1, 5)]]:
        output, warnings = wsl(["iverilog", "-g2012", "-s", "tb_host_stop",
            f"-Ptb_host_stop.STOP_STATE={state}", f"-Ptb_host_stop.USE_VPA={vpa}",
            f"-Ptb_host_stop.ENABLE={enable}", f"-Ptb_host_stop.HOLD_ACK={held}",
            f"-Ptb_host_stop.INJECT_BERR={berr}", "-o", linux(binary), *map(linux, sources)])
        assert not warnings, warnings
        dump = WORK / f"memory-{state}-{vpa}-{enable}-{held}-{berr}.hex"
        output, warnings = wsl(["vvp", linux(binary), "+dump=" + linux(dump)])
        assert "PASS host-stop" in output and not warnings, output + warnings
        words = [line.strip() for line in dump.read_text(encoding="ascii").splitlines()
                 if line.strip() and not line.startswith("//")]
        assert len(words) == 2048 and all(len(word) == 4 for word in words)
        memory = bytes.fromhex("".join(words))
        if baseline_memory is None:
            baseline_memory = memory
        assert memory == baseline_memory, "full 4KiB memory comparison"
        print(output)
        runs.append(output)
    for name, pin in PINS.items():
        assert hashlib.sha256((MACLC / "rtl/tg68k" / name).read_bytes()).hexdigest() == pin
    inputs = [HERE / "prepare.py", HERE / "run.py", *sources]
    (HERE / "results.json").write_text(json.dumps({
        "scope": "Actual translated kernel and wrapper; synthetic memory responder",
        "source_pins": PINS, "runs": runs,
        "memory_bytes_compared_per_run": len(baseline_memory),
        "memory_sha256": hashlib.sha256(baseline_memory).hexdigest(),
        "reference_sources_unchanged": True,
        "inputs_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
