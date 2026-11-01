#!/usr/bin/env python3
"""Fixed-window comparison of isolated clock, byte-mask and admission experiments."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/card-memory-timing"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr.strip()


def timing(path):
    rows = [line.split() for line in path.read_text().splitlines()]
    result = {}
    for write, label in ((0, "read"), (1, "write")):
        values = [round(float(row[4]) - float(row[3]), 3) for row in rows if int(row[1]) == write]
        result[label] = {"count": len(values), "median_ns": statistics.median(values), "max_ns": max(values),
                         "over_1_02mhz": sum(v > 1e9 / 1020000 for v in values),
                         "over_1_9mhz": sum(v > 1e9 / 1900000 for v in values)}
    return result


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    byte_dir = ROOT / "fixtures/experiments/native-byte-memory"
    byte_script = byte_dir / "prepare.py"
    fair_script = ROOT / "fixtures/experiments/native-admission/run.py"
    byte = load(byte_script, "byte_support")
    fair = load(fair_script, "fair_admission")
    controller = Path("C:/Workspace/Git/MacLC_MiSTer/rtl/sdram.v")
    assert sha(controller) == byte.PIN == fair.SOURCE_SHA
    patched_controller = WORK / "sdram.v"
    patched_controller.write_text(byte.byte_support(fair.patched(controller.read_text(encoding="utf-8"))), encoding="utf-8", newline="\n")
    candidate_source = ROOT / "fixtures/experiments/card-system-harness/card_candidate.sv"
    candidate = candidate_source.read_text().replace("module card_candidate (", "module card_byte_candidate (")
    candidate = candidate.replace("    output wire [15:0] mem_wdata,", "    output wire [15:0] mem_wdata,\n    output wire [1:0] mem_be,")
    candidate = candidate.replace("    card_memory_arbiter memory (", "    card_byte_memory_arbiter memory (")
    candidate = candidate.replace(".mem_wdata(mem_wdata), .mem_rsp_valid", ".mem_wdata(mem_wdata), .mem_be(mem_be), .mem_rsp_valid")
    candidate_path = WORK / "card_byte_candidate.sv"
    candidate_path.write_text(candidate, encoding="ascii")
    placement = ROOT / "fixtures/experiments/card-clock-placement"
    wrapper_source = placement / "card_frontend_platform.sv"
    wrapper = wrapper_source.read_text().replace("module card_frontend_platform #(", "module card_byte_frontend_platform #(")
    wrapper = wrapper.replace("    output wire [15:0] native_din,", "    output wire [15:0] native_din,\n    output wire [1:0] native_ds,")
    wrapper = wrapper.replace("    wire card_req, card_we;", "    wire card_req, card_we;\n    wire [1:0] dst_be, card_ds;")
    wrapper = wrapper.replace("    card_candidate card (", "    card_byte_candidate card (")
    wrapper = wrapper.replace("    card_native_memory_adapter #(", "    card_byte_native_adapter #(")
    wrapper = wrapper.replace("    card_native_port_mux ownership (", "    card_byte_native_port_mux ownership (")
    wrapper = wrapper.replace(".mem_wdata(dst_wdata),", ".mem_wdata(dst_wdata), .mem_be(dst_be),")
    wrapper = wrapper.replace(".native_din(card_din),", ".native_din(card_din), .native_ds(card_ds),")
    wrapper = wrapper.replace(".card_din(card_din),", ".card_din(card_din), .card_ds(card_ds), .floppy_ds(2'b11),")
    wrapper = wrapper.replace(".native_din(native_din),", ".native_din(native_din), .native_ds(native_ds),")
    wrapper_path = WORK / "card_byte_frontend_platform.sv"
    wrapper_path.write_text(wrapper, encoding="ascii")
    qip = ROOT / "fixtures/experiments/card-platform/card_platform.qip"
    closure = [(qip.parent / name).resolve() for name in re.findall(r"\[file join \$::quartus\(qip_path\) ([^\]]+)\]", qip.read_text())]
    assert len(closure) == 12
    tb = HERE / "tb_card_memory_timing.sv"
    paths = [tb, *closure, placement / "card_host_cdc.sv", wrapper_source, candidate_path, wrapper_path,
             *[byte_dir / name for name in ("card_byte_memory_arbiter.sv", "card_byte_native_adapter.sv", "card_byte_native_port_mux.sv")],
             patched_controller]
    generated = ROOT / "local/experiments/card-system-harness"
    stimulus, expected = generated / "stimulus0.txt", generated / "expected0.hex"
    runs = []
    for name, flags, enabled, fair_enabled in (("backend_baseline", ["-DBACKEND_PATH"], 0, 0),
                                              ("frontend_baseline", [], 0, 0),
                                              ("frontend_byte", ["-DBYTE_PATH"], 1, 0),
                                              ("frontend_byte_fair", ["-DBYTE_PATH"], 1, 1)):
        executable = WORK / f"{name}.vvp"
        parameters = [f"-Ptb_card_memory_timing.BYTE_ENABLE={enabled}", f"-Ptb_card_memory_timing.FAIR={fair_enabled}"]
        wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", *flags, *parameters, "-s", "tb_card_memory_timing", "-o", linux(executable), *map(linux, paths)])
        trace, latency = WORK / f"{name}-captures.txt", WORK / f"{name}-latency.txt"
        output, errors = wsl(["vvp", linux(executable), f"+stimulus={linux(stimulus)}", f"+expected={linux(expected)}",
                              f"+trace={linux(trace)}", f"+latency={linux(latency)}"])
        assert output.startswith("PASS ") and not errors, output + errors
        assert sha(trace) == "77f7eb7ce43f16cb5d66b8491b8c1783e21a0259ee4551c784e6dbe8e1e45246"
        runs.append({"variant": name, "result": output, "ordinary": timing(latency),
                     "latency_trace_sha256": sha(latency), "capture_trace_sha256": sha(trace)})
        print(json.dumps(runs[-1], indent=2))
    inputs = [*paths, Path(__file__).resolve(), controller, byte_script, fair_script, candidate_source, qip, stimulus, expected]
    result = {"scope": "Identical absolute demand-window finite timing comparison", "runs": runs,
              "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"): sha(p) for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
