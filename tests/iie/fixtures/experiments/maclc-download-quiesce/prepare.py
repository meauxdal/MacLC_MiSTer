#!/usr/bin/env python3
"""Extract pinned MacLC download logic; generate isolated drain candidate."""

import hashlib
import importlib.util
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/maclc-download-quiesce"
MACLC = Path("C:/Workspace/Git/MacLC_MiSTer")
PINS = {
    "MacLC.sv": "3bafa309638a9325cbff5401b06402d066b9e8ac2340aafacf14549617a7e1f0",
    "rtl/sdram.v": "953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04",
}

PORTS = """(
    input wire clk_sys, pll_locked_s, stop, hps_fenced,
    input wire loader_stopped, committer_stopped,
    input wire ioctl_write, dio_download,
    input wire [15:0] ioctl_data,
    input wire [23:0] dio_addr,
    input wire flp_int_wr_req,
    input wire [23:0] flp_int_wr_addr,
    input wire [15:0] flp_int_wr_data,
    input wire wc_req,
    input wire [21:0] wc_addr,
    input wire [15:0] wc_data,
    input wire dioBusControl, sdram_dl_ack,
    output wire ioctl_wait, local_drained, stopped,
    output reg protocol_fault,
    output wire flp_int_wr_ack, wc_ack,
    output reg sdram_dlreq_q, sdram_dlslot_q,
    output reg [23:0] sdram_dladdr_q,
    output reg [15:0] sdram_dldin_q
);
"""


def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


def prepare():
    original = {}
    for name, pin in PINS.items():
        raw = (MACLC / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == pin, name
        original[name] = raw.decode("utf-8").replace("\r\n", "\n")
    WORK.mkdir(parents=True, exist_ok=True)
    mac = original["MacLC.sv"]
    start = mac.index("\treg [22:0] dio_a;")
    end = mac.index("\n\t// (Floppy-download acceptance counters", start)
    ingress_mux = mac[start:end]
    # Keep the exact DL request bundle pipeline from the real top level.
    register = mac[mac.index("\t\tsdram_dlreq_q    <= dl_req_mux;"):]
    register = register[:register.index("\n\tend")]
    assert len(register.splitlines()) == 4
    (WORK / "pinned-ingress-mux.txt").write_text(ingress_mux, encoding="utf-8")
    (WORK / "pinned-request-register.txt").write_text(register, encoding="ascii")

    source = ingress_mux
    source = replace(source, "\twire        sdram_dl_ack;", "")
    begin = source.index("\talways @(posedge clk_sys) begin")
    end = source.index("\n\t// -- SDRAM download-port arbitration", begin)
    source = source[:begin] + """    reg rom_pending;
    wire dl_rom_sel;
    assign ioctl_wait = stop || rom_pending || dl_rom_sel || protocol_fault;
    always @(posedge clk_sys) begin
        if (!pll_locked_s) begin
            rom_pending <= 0;
            protocol_fault <= 0;
            dio_a <= 0;
            dio_data <= 0;
        end else begin
            if (ioctl_write) begin
                if (rom_pending || (dl_locked && dl_grant == DLG_ROM)) protocol_fault <= 1;
                else begin
                    dio_data <= {ioctl_data[7:0], ioctl_data[15:8]};
                    dio_a <= {5'b10100, dio_addr[17:0]};
                    rom_pending <= 1;
                end
            end else if (sdram_dl_ack && dl_rom_sel) rom_pending <= 0;
        end
    end
""" + source[end:]
    begin = source.index("\tlocalparam DLG_LDR")
    end = source.index("\n\t// The committer emits", begin)
    source = source[:begin] + """    localparam DLG_LDR = 2'd0, DLG_WC = 2'd1, DLG_ROM = 2'd2;
    reg [1:0] dl_grant;
    reg dl_locked;
    reg dl_released;
    reg [23:0] dl_addr_hold;
    reg [15:0] dl_data_hold;
`ifdef UNSAFE_WAIT_REQUEST
    wire selected_req = dl_grant == DLG_ROM ? ioctl_wait :
`else
    wire selected_req = dl_grant == DLG_ROM ? rom_pending :
`endif
                        dl_grant == DLG_WC ? wc_req : flp_int_wr_req;
    always @(posedge clk_sys) begin
        if (!pll_locked_s) begin
            dl_grant <= DLG_LDR;
            dl_locked <= 0;
            dl_released <= 0;
            dl_addr_hold <= 0;
            dl_data_hold <= 0;
        end else if (dl_locked) begin
            // Retain ownership through the registered request and ACK-low tail.
            if (!selected_req) dl_released <= 1;
            if (dl_released && !sdram_dlreq_q && !sdram_dl_ack)
                dl_locked <= 0;
        end else if (!sdram_dlreq_q && !sdram_dl_ack) begin
            dl_released <= 0;
            if (rom_pending) begin
                dl_grant <= DLG_ROM;
                dl_locked <= 1;
                dl_addr_hold <= {1'b0, dio_a};
                dl_data_hold <= dio_data;
            end else if (flp_int_wr_req) begin
                dl_grant <= DLG_LDR;
                dl_locked <= 1;
                dl_addr_hold <= flp_int_wr_addr;
                dl_data_hold <= flp_int_wr_data;
            end else if (wc_req) begin
                dl_grant <= DLG_WC;
                dl_locked <= 1;
                dl_addr_hold <= wc_word_addr;
                dl_data_hold <= wc_data;
            end
        end
    end
`ifdef UNSAFE_ROM_OVERRIDE
    assign dl_rom_sel = dio_download;
`else
    assign dl_rom_sel = dl_locked && dl_grant == DLG_ROM;
`endif
    wire dl_ldr_sel = dl_locked && dl_grant == DLG_LDR && !dl_rom_sel;
    wire dl_wc_sel = dl_locked && dl_grant == DLG_WC && !dl_rom_sel;
""" + source[end:]
    begin = source.index("\twire        dl_req_mux")
    end = source.index("\n\twire flp_int_wr_ack", begin)
    source = source[:begin] + """`ifdef UNSAFE_WAIT_REQUEST
    wire rom_req = ioctl_wait;
`else
    wire rom_req = rom_pending;
`endif
    wire dl_req_mux = !dl_released && (dl_rom_sel ? rom_req :
                      dl_wc_sel ? wc_req : dl_ldr_sel && flp_int_wr_req);
`ifdef UNSAFE_ROM_OVERRIDE
    wire [23:0] dl_addr_mux = dl_rom_sel ? {1'b0, dio_a} : dl_addr_hold;
    wire [15:0] dl_data_mux = dl_rom_sel ? dio_data : dl_data_hold;
`else
    wire [23:0] dl_addr_mux = dl_addr_hold;
    wire [15:0] dl_data_mux = dl_data_hold;
`endif
""" + source[end:]
    source = replace(source, "\twire flp_int_wr_ack =", "\tassign flp_int_wr_ack =")
    source = replace(source, "sdram_dl_ack && dl_ldr_sel;", "sdram_dl_ack && dl_ldr_sel && dl_ack_enabled;")
    source = replace(source, "sdram_dl_ack && dl_wc_sel;", "sdram_dl_ack && dl_wc_sel && dl_ack_enabled;")
    # Remove inherited prose; preserve extracted statements and brief constraints.
    source = "\n".join(line.split("//")[0].rstrip() for line in source.splitlines())
    source = re.sub(r"\n\s*\n(?:\s*\n)+", "\n\n", source)
    source += """
`ifdef UNSAFE_RELEASE_ACK
    wire dl_ack_enabled = 1'b1;
`else
    wire dl_ack_enabled = !dl_released;
`endif
    assign local_drained = !rom_pending && !ioctl_write && !dl_locked &&
                           !flp_int_wr_req && !wc_req && !dl_req_mux &&
                           !sdram_dlreq_q && !sdram_dl_ack && !protocol_fault;
    // hps_fenced requires a transport acknowledgment absent from existing HPS IO.
    assign stopped = stop && hps_fenced && !dio_download && loader_stopped &&
                     committer_stopped && local_drained;
    always @(posedge clk_sys) begin
""" + register + "\n    end\n"
    # Cold initialization only. Warm reset must never clear a captured word.
    source = replace(source, "\t\tsdram_dlreq_q    <= dl_req_mux;",
                     "\t\tsdram_dlreq_q    <= pll_locked_s && dl_req_mux;")
    (WORK / "maclc_download.sv").write_text("module maclc_download " + PORTS + source + "\nendmodule\n", encoding="ascii")
    spec = importlib.util.spec_from_file_location("controller_quiesce", HERE.parent / "card-quiesce/prepare.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    (WORK / "sdram.v").write_text(helper.quiesce_support(original["rtl/sdram.v"]), encoding="utf-8")


if __name__ == "__main__":
    prepare()
