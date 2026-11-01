#!/usr/bin/env python3
"""Pinned optional TG68K bus-boundary pause; generated sources stay local."""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MACLC = ROOT.parent / "MacLC_MiSTer"
WORK = ROOT / "local/experiments/maclc-host-quiesce"
PINS = {
    "tg68k.v": "262b972c8136e0351bc44e41b8cb1a72224a37e4a8da6a444f7a97464f32f195",
    "TG68KdotC_Kernel.v": "219a9fab81611570f9e8733e7ee5aaf683b03d60dfd75426ab5f55c738043406",
}


def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for name, pin in PINS.items():
        data = (MACLC / "rtl/tg68k" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == pin, name
        if name != "tg68k.v":
            continue
        source = data.decode("utf-8").replace("\r\n", "\n")
        source = replace(source, "module tg68k (", "module tg68k #(parameter QUIESCE = 0) (")
        source = replace(source, "\tinput reset,", "\tinput reset,\n\tinput stop_req,\n\toutput stopped,")
        source = replace(source, "wire  [1:0] tg68_busstate;", """wire  [1:0] tg68_busstate;
wire stopping = QUIESCE && stop_req;
reg [1:0] quiet_ticks;
assign stopped = QUIESCE && stopping && quiet_ticks == 3 && !reset;
always @(posedge clk) begin
    if (reset || !stopping || s_state != S_IDLE || !dtack_n || !vma_n || berr_held)
        quiet_ticks <= 0;
    else if (quiet_ticks != 3)
        quiet_ticks <= quiet_ticks + 1'b1;
end
""")
        source = replace(source, "(s_state == S_IDLE && tg68_busstate == 2'b01 && !clkena_d)",
                         "(s_state == S_IDLE && !stopping && tg68_busstate == 2'b01 && !clkena_d)")
        source = replace(source, "if (tg68_busstate != 2'b01 && !(busreq_ack || bus_granted)) begin",
                         "if (!stopping && tg68_busstate != 2'b01 && !(busreq_ack || bus_granted)) begin")
        (WORK / name).write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
