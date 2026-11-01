#!/usr/bin/env python3
"""Source-pinned optional admission experiment; no live controller edits."""
import difflib
import hashlib
import json
import re
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "local/experiments/native-admission"
MAC = ROOT.parent / "MacLC_MiSTer"
SOURCE_SHA = "953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04"


def patched(original):
    code = original.replace("module sdram \n(\n", "module sdram #(parameter FAIR_NATIVE_ADMISSION = 0)\n(\n", 1)
    assert code != original
    code = code.replace("reg        src_eth;", "reg        prefer_native;\nreg        src_eth;", 1)
    code = code.replace("eth_req && !eth_ack && !(oe || we)",
                        "eth_req && !eth_ack && (FAIR_NATIVE_ADMISSION || !(oe || we))", 1)
    marker = "\n\nalways @(posedge clk_64) begin\n\tsd_cmd <= CMD_INHIBIT;"
    assert marker in code
    code = code.replace(marker,
                        "\nwire grant_cpu = req_cpu && (!FAIR_NATIVE_ADMISSION || !req_eth || !prefer_native);"
                        + marker, 1)
    code = code.replace("\t\tsrc_eth    <= 0;", "\t\tsrc_eth    <= 0;\n\t\tprefer_native <= 0;", 1)
    start = code.index("\t\tend else if (req_flp || req_dl || req_cpu || req_eth) begin")
    end = code.index("\t\tend else if (ref_due >= REF_OPP", start)
    block = code[start:end]
    block = block.replace("req_cpu", "grant_cpu")
    old_comment = "\t\t\t// start priority: floppy window > download > CPU > ethernet DMA\n\t\t\t// (req_eth already excludes any live CPU level, so the eth leg of\n\t\t\t// these muxes can only be reached with the other three false)"
    assert old_comment in block
    block = block.replace(old_comment,
                          "\t\t\t// Floppy/download retain priority; optional CPU/native round robin.\n"
                          "\t\t\tif (!req_flp && !req_dl) prefer_native <= grant_cpu;")
    return code[:start] + block + code[end:]


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return (result.stdout + result.stderr).strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    source = MAC / "rtl/sdram.v"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA, "controller source changed"
    original = source.read_text(encoding="utf-8")
    modified = patched(original)
    scratch = WORK / "sdram.v"
    scratch.write_text(modified, encoding="utf-8", newline="\n")
    patch = "".join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
                                       fromfile="a/rtl/sdram.v", tofile="b/rtl/sdram.v", n=1))
    (HERE / "fair-native.patch").write_text(patch, encoding="utf-8", newline="\n")
    bench = HERE / "tb_native_admission.sv"
    stub = MAC / "verilator/altddio_out_stub.v"
    assert stub.is_file(), "expected local SDRAM clock stub missing"
    runs = []
    for fair in (0, 1):
        target = WORK / f"admission{fair}.vvp"
        wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE", "-s", "tb_native_admission",
             f"-Ptb_native_admission.FAIR={fair}", "-o", linux(target), linux(bench), linux(scratch), linux(stub)])
        result = wsl(["vvp", linux(target)])
        assert result.startswith("PASS "), result
        runs.append({"fair": fair, "result": result})
    seam = MAC / "verilator/tb_icache_seam.v"
    assert seam.is_file(), "expected local icache seam regression missing"
    seam_runs = []
    for fair in (0, 1):
        for negative in (0, 1):
            seam_scratch = WORK / f"tb_icache_seam{fair}.v"
            seam_text = seam.read_text(encoding="utf-8")
            assert "sdram dut (" in seam_text
            seam_text = seam_text.replace("sdram dut (", f"sdram #(.FAIR_NATIVE_ADMISSION({fair})) dut (", 1)
            seam_text = seam_text.replace("\t.dl_ack(dl_ack),", "\t.dl_ack(dl_ack),\n"
                                          "\t.eth_req(1'b0), .eth_we(1'b0), .eth_addr(24'b0), .eth_din(16'b0),\n"
                                          "\t.eth_ack(), .eth_dout(),", 1)
            seam_scratch.write_text(seam_text, encoding="utf-8")
            target = WORK / f"seam{fair}-{negative}.vvp"
            wsl(["iverilog", "-g2012", "-DTB_NO_TRISTATE",
                 *(["-DSDRAM_NO_DONE_LEVEL_FIX"] if negative else []),
                 "-s", "tb_icache_seam", "-o", linux(target), linux(seam_scratch), linux(scratch), linux(stub)])
            result = wsl(["vvp", linux(target)])
            assert ("RESULT: FAIL" if negative else "RESULT: PASS") in result, result
            counts = re.search(r"checks=(\d+) errors=(\d+) stale_done_violations=(\d+)", result)
            assert counts and int(counts[1]) > 0
            assert int(counts[3]) > 0 if negative else int(counts[2]) == 0
            (WORK / f"icache{fair}-{negative}.log").write_text(result + "\n", encoding="utf-8")
            seam_runs.append({"fair": fair, "stale_done_negative": bool(negative),
                              "result": "expected FAIL" if negative else "PASS",
                              "checks": int(counts[1]), "errors": int(counts[2]),
                              "stale_done_violations": int(counts[3])})
    inputs = [Path(__file__), bench, HERE / "fair-native.patch", source, seam, stub]
    result = {"scope": "optional source-pinned native admission patch; command model, not hardware timing proof",
              "runs": runs, "icache_seam": seam_runs,
              "scratch_sha256": hashlib.sha256(scratch.read_bytes()).hexdigest(),
              "inputs_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):
                                hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
