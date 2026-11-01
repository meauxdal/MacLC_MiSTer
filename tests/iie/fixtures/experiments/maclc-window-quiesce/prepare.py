#!/usr/bin/env python3
"""Pinned optional floppy-window stop; reference sources remain unchanged."""

import hashlib
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/maclc-window-quiesce"
MACLC = Path("C:/Workspace/Git/MacLC_MiSTer")
PINS = {
    "rtl/addrController_top.v": "b9f619a0378bce1bd057c71645814be26ae46d5222688776dd2987fc51e95f78",
    "rtl/floppy.v": "6d476e367e1eda093982d52c2cf57053e32819b317f4d01866978ec35bd56dbd",
    "MacLC.sv": "3bafa309638a9325cbff5401b06402d066b9e8ac2340aafacf14549617a7e1f0",
    "rtl/sdram.v": "953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04",
}


def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


def prepare():
    originals = {}
    for name, pin in PINS.items():
        data = (MACLC / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == pin, name
        originals[name] = data.decode("utf-8").replace("\r\n", "\n")
    WORK.mkdir(parents=True, exist_ok=True)
    source = originals["rtl/addrController_top.v"]
    source = replace(source, "module addrController_top(", """module addrController_top #(
    parameter ENABLE_WARM_STOP = 0
) (
    input warm_reset,
    input warm_stop,
    output warm_stopped,""")
    source = replace(source, "\twire flp_ok = !dio_download && flp_present;", """    reg flp_paused;
    wire stop_enabled = ENABLE_WARM_STOP && warm_stop;
    always @(posedge clk) begin
        if (warm_reset) flp_paused <= 1;
        else if (!stop_enabled) flp_paused <= 0;
        else if (!flp_guard && !dskReadAckInt && !dskReadAckExt)
            flp_paused <= 1;
    end
    assign warm_stopped = stop_enabled && flp_paused;
\twire flp_ok = !dio_download && flp_present && !(ENABLE_WARM_STOP && flp_paused);""")
    (WORK / "addrController_top.v").write_text(source, encoding="utf-8")
    original = replace(originals["rtl/addrController_top.v"],
                       "module addrController_top(", "module baseline_addrController_top(")
    (WORK / "baseline_addrController_top.v").write_text(original, encoding="utf-8")
    # Exact consumer pipeline, without its unrelated encoder and write machinery.
    floppy = originals["rtl/floppy.v"]
    start = floppy.index("\treg dskReadAckD;")
    end = floppy.index("\t\t\n\twire [7:0] dskReadDataEnc;", start)
    consumer = floppy[start:end].replace("reg dskReadAckD;", "").replace("reg [7:0] dskReadDataLatch;", "")
    (WORK / "floppy_read_tail.sv").write_text("""module floppy_read_tail (
    input wire clk, cen, cep, dskReadAck,
    input wire [7:0] dskReadData,
    output reg dskReadAckD,
    output reg [7:0] dskReadDataLatch
);
""" + consumer + "\nendmodule\n", encoding="ascii")
    spec = importlib.util.spec_from_file_location("card_quiesce_controller", HERE.parent / "card-quiesce/prepare.py")
    quiesce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quiesce)
    (WORK / "sdram.v").write_text(quiesce.quiesce_support(originals["rtl/sdram.v"]), encoding="utf-8")
    return originals


if __name__ == "__main__":
    prepare()
