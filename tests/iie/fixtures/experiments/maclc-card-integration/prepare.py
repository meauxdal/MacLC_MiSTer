#!/usr/bin/env python3
"""Generate and apply-check dormant hookup seams against the pinned MacLC."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASELINE = Path("C:/Workspace/Git/MacLC_MiSTer")
WORK = ROOT / "local/experiments/maclc-card-integration"
PINNED = {
    "MacLC.sv": "3bafa309638a9325cbff5401b06402d066b9e8ac2340aafacf14549617a7e1f0",
    "files.qip": "2dfeea36a23f868d079b2361ffc2507f654bd584a530839b8a4155f6234d303d",
}
GUARD = "APPLE_IIE_CARD_DORMANT_SEAMS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="refused: live integration is not implemented")
    args = parser.parse_args()
    if args.enable:
        parser.error("activation blocked: quiesce/reinit, SDRAM reservation, CDC constraints, native admission, "
                     "TG68 error recovery and remaining diagnostic behavior are unresolved")
    original = {}
    for name, expected in PINNED.items():
        data = (BASELINE / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"baseline hash mismatch: {name}; review source before regenerating")
        original[name] = data.decode("utf-8")
    modified = dict(original)
    nl = "\r\n" if "\r\n" in original["MacLC.sv"] else "\n"

    def replace_once(before, after):
        assert modified["MacLC.sv"].count(before) == 1, before
        modified["MacLC.sv"] = modified["MacLC.sv"].replace(before, after)

    def guarded(before, after):
        replace_once(before, f"`ifdef {GUARD}{nl}" + after + nl + "`else" + nl +
                     before + nl + "`endif")

    replace_once("\twire _ramOE, _ramWE;", "\twire _ramOE, _ramWE;" + nl + nl.join([
        "", f"`ifdef {GUARD}",
        "\t// Dormant seams only. No card instance or live activation is provided.",
        "\twire iie_card_claim_raw = 1'b0;",
        "\twire iie_card_claim = iie_card_claim_raw && !_cpuAS && cpuFC != 3'b111;",
        "\twire iie_card_dtack_n = 1'b1;",
        "\twire iie_card_error = 1'b0;",
        "\twire [15:0] iie_card_read_data = 16'hFFFF;",
        "\twire iie_rom_oe_raw, iie_ram_oe_raw, iie_ram_we_raw;",
        "\tassign _romOE = iie_rom_oe_raw || iie_card_claim;",
        "\tassign _ramOE = iie_ram_oe_raw || iie_card_claim;",
        "\tassign _ramWE = iie_ram_we_raw || iie_card_claim;",
        "`endif",
    ]))
    guarded("\t\t.pds_claim(1'b0),", "\t\t.pds_claim(iie_card_claim),")
    for signal, raw in (("_romOE", "iie_rom_oe_raw"), ("_ramOE", "iie_ram_oe_raw"),
                        ("_ramWE", "iie_ram_we_raw")):
        guarded(f"\t\t.{signal}({signal}),", f"\t\t.{signal}({raw}),")
    line = next(line for line in modified["MacLC.sv"].splitlines() if "assign      _cpuVPA =" in line)
    guarded(line, line.replace("fc7_berr || slot_space", "fc7_berr || slot_space || iie_card_claim"))
    line = "\tassign      _cpuDTACK = fc7_berr ? 1'b1 :"
    guarded(line, line + nl +
            "\t                        iie_card_claim ? (iie_card_error ? 1'b1 : iie_card_dtack_n) :")
    line = "\twire cpu_berr = (fc7_berr && !_cpuAS) || sdma_berr;"
    guarded(line, line[:-1] + " || (iie_card_claim && iie_card_error);")
    guarded("\t\t.cacheable  ( selectRAM || selectROM ),",
            "\t\t.cacheable  ( !iie_card_claim && (selectRAM || selectROM) ),")
    guarded("\t\t.snoopable  ( selectRAM ),", "\t\t.snoopable  ( !iie_card_claim && selectRAM ),")
    line = "\twire [15:0] cpu_din_muxed = slot_space     ? 16'hFFFF :"
    guarded(line, "\twire [15:0] cpu_din_muxed = iie_card_claim ? iie_card_read_data :" + nl +
            "\t                            slot_space     ? 16'hFFFF :")
    replace_once("\twire        flp_mem_req, flp_mem_ack;", "\twire        flp_mem_req, flp_mem_ack;" + nl + nl.join([
        "", f"`ifdef {GUARD}",
        "\t// Native pass-through until a reviewed card_platform binding exists.",
        "\twire iie_native_req = flp_mem_req;",
        "\twire iie_native_we = 1'b0;",
        "\twire [23:0] iie_native_addr = flp_mem_addr;",
        "\twire [15:0] iie_native_din = 16'b0;",
        "\twire iie_native_ack;",
        "\twire [15:0] iie_native_dout;",
        "\tassign flp_mem_ack = iie_native_ack;",
        "\tassign flp_mem_dout = iie_native_dout;",
        "`endif",
    ]))
    native_lines = [line for line in modified["MacLC.sv"].splitlines()
                    if line.lstrip().startswith(".eth_")]
    assert len(native_lines) == 6
    for line in native_lines:
        replacement = line
        for before, after in (("flp_mem_req", "iie_native_req"), ("1'b0", "iie_native_we"),
                              ("flp_mem_addr", "iie_native_addr"), ("16'd0", "iie_native_din"),
                              ("flp_mem_ack", "iie_native_ack"), ("flp_mem_dout", "iie_native_dout")):
            replacement = replacement.replace(before, after)
        guarded(line, replacement)

    qnl = "\r\n" if "\r\n" in original["files.qip"] else "\n"
    modified["files.qip"] += qnl + qnl.join([
        "# Review seams only. Live card activation is intentionally blocked.",
        "if {[info exists ::env(APPLE_IIE_CARD_ENABLE)]} {",
        '    error "IIe Card activation blocked: resolve reset, allocation, SDC, admission and diagnostic gates"',
        "}",
        "if {0} {",
        f"    set_global_assignment -name VERILOG_MACRO {GUARD}",
        "    set_global_assignment -name QIP_FILE [file join $::quartus(qip_path) ../Apple-IIe-Card/fixtures/experiments/card-platform/card_platform.qip]",
        "}", "",
    ])
    def select_guard(match):
        before, separator, after = match.group(1).partition("`else" + nl)
        return after if separator else ""

    without_guard = re.sub(rf"^`ifdef {GUARD}\r?\n(.*?)^`endif\r?\n", select_guard,
                           modified["MacLC.sv"], flags=re.MULTILINE | re.DOTALL)
    nonblank = lambda text: [line for line in text.splitlines() if line.strip()]
    assert nonblank(without_guard) == nonblank(original["MacLC.sv"]), "guard-off source changed"
    patch = "".join("".join(difflib.unified_diff(original[name].splitlines(keepends=True),
                                               modified[name].splitlines(keepends=True),
                                               fromfile="a/" + name, tofile="b/" + name))
                    for name in PINNED)
    (HERE / "dormant-hookup.patch").write_bytes(patch.encode("utf-8"))
    WORK.mkdir(parents=True, exist_ok=True)
    for name in PINNED:
        (WORK / name).write_bytes(original[name].encode("utf-8"))
    directory = WORK.relative_to(ROOT).as_posix()
    for check in (True, False):
        command = ["git", "apply", "--whitespace=nowarn", f"--directory={directory}"]
        if check:
            command.append("--check")
        command.append(str(HERE / "dormant-hookup.patch"))
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=10)
    for name in PINNED:
        assert (WORK / name).read_bytes() == modified[name].encode("utf-8"), name
        assert hashlib.sha256((BASELINE / name).read_bytes()).hexdigest() == PINNED[name]
    result = {"baseline": "07770d622facce6215dc98daa197511286817825", "mode": "dormant only",
              "patch_applies": True, "scratch_matches_transform": True, "baseline_unchanged": True,
              "guard_off_nonblank_source_identical": True,
              "activation_available": False, "baseline_sha256": PINNED,
              "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
              "patched_sha256": {name: hashlib.sha256(modified[name].encode("utf-8")).hexdigest()
                                 for name in PINNED},
              "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print("PASS source hashes, git apply --check, scratch application and unchanged MacLC; activation blocked")


if __name__ == "__main__":
    main()
