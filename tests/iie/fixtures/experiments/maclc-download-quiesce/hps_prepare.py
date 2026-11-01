#!/usr/bin/env python3
"""Extract pinned HPS file framing and the actual top-level wait handshake."""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/maclc-download-quiesce"
REFERENCE = Path("C:/Workspace/Git/MacLC_MiSTer")
PINS = {
    "sys/hps_io.sv": "fc939385b3fdd920e70de93b37e4bbde2ed759bba4f7888bde67f577814e708f",
    "sys/sys_top.v": "171b9f9afc14da5d84b6721bb3e0649857f22ba9c4d2c416a73c69a21cb06b4e",
}


def prepare():
    sources = {}
    for name, pin in PINS.items():
        raw = (REFERENCE / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == pin, name
        sources[name] = raw.decode("utf-8").replace("\r\n", "\n")
    hps = sources["sys/hps_io.sv"]
    fio = hps[hps.index("localparam FIO_FILE_TX "):hps.index("\nendmodule", hps.index("localparam FIO_FILE_TX "))]
    top = sources["sys/sys_top.v"]
    start = top.index("reg  io_ack;")
    handshake = top[start:top.index("\nreg [31:0] gp_outr;", start)]
    # Only standalone declarations are supplied; both clocked source blocks are exact.
    source = """module hps_protocol_source(
    input clk_sys, io_clk, fp_enable, io_enable, ioctl_wait,
    input [15:0] io_din,
    output io_ack_out, io_strobe_out,
    output reg ioctl_download = 0,
    output reg ioctl_upload = 0,
    output reg ioctl_wr,
    output reg ioctl_rd,
    output reg [26:0] ioctl_addr,
    output reg [15:0] ioctl_dout,
    output reg [15:0] ioctl_index,
    output reg [31:0] ioctl_file_ext
);
localparam WIDE = 1;
localparam DW = 15;
wire [15:0] ioctl_din = 0;
wire vs_wait = 0;
wire io_wait = ioctl_wait;
assign io_ack_out = io_ack;
assign io_strobe_out = io_strobe;
""" + handshake + "\n" + fio + "\nendmodule\n"
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "hps_protocol_source.sv"
    path.write_text(source, encoding="ascii")
    return path


if __name__ == "__main__":
    print(prepare())
