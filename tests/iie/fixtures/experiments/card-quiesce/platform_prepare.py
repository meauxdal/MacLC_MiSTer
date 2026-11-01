#!/usr/bin/env python3
"""Isolated real-endpoint platform; frozen source closure stays unchanged."""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-quiesce/endpoints"


def replace(source, before, after):
    assert source.count(before) == 1, before
    return source.replace(before, after)


def prepare():
    path = ROOT / "fixtures/experiments/card-platform/card_platform.sv"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "64002ab0ccb5fb08634dae5c7c41bdc9b8f7df20b3804a44ac8d2f0bf3d49d44"
    source = path.read_text()
    source = replace(source, "    input wire host_reset,", """    input wire host_reset,
    input wire stop_request,
    input wire controller_ready_mem,
    input wire controller_quiesce,
    input wire epoch_reset_sys,
    input wire epoch_reset_mem,
    output wire producers_stopped,
    output wire source_drained,
    output wire native_drained,""")
    source = replace(source, "    card_pds_candidate card (", """    wire cpu_stopped, pds_stopped, endpoint_drained, floppy_stopped;
    wire card_cdc_drained, floppy_cdc_drained, adapter_drained, mux_drained;
    wire floppy_offer, floppy_ready, floppy_source_response, floppy_source_ready;
    wire [23:0] floppy_source_addr;
    (* ASYNC_REG = "TRUE" *) reg ready_sync1, ready_sync2;
    wire stop_sources = stop_request || !ready_sync2;
    always @(posedge clk_sys) begin
        if (!por_n_sys) begin
            ready_sync1 <= 0;
            ready_sync2 <= 0;
        end else begin
            ready_sync1 <= controller_ready_mem;
            ready_sync2 <= ready_sync1;
        end
    end
    assign producers_stopped = cpu_stopped && pds_stopped && floppy_stopped;
    assign source_drained = endpoint_drained && card_cdc_drained &&
                            floppy_cdc_drained && floppy_stopped;
    assign native_drained = adapter_drained && mux_drained &&
                            !floppy_active && !floppy_response_valid && !dst_valid && !floppy_dst_valid;
    card_floppy_stop floppy_ingress (
        .clk(clk_sys), .reset(!por_n_sys), .stop_request(stop_sources), .stopped(floppy_stopped),
        .req(floppy_req), .addr(floppy_addr), .ack(floppy_ack),
        .valid(floppy_offer), .ready(floppy_ready), .frozen_addr(floppy_source_addr),
        .rsp_valid(floppy_source_response), .rsp_ready(floppy_source_ready),
        .mailbox_drained(floppy_cdc_drained)
    );
    card_pds_candidate card (""")
    source = replace(source, ".clk(clk_sys), .por_n(por_n_sys), .host_reset(host_reset),", """.clk(clk_sys), .por_n(por_n_sys), .host_reset(host_reset),
        .stop_request(stop_sources), .cpu_stopped(cpu_stopped), .pds_stopped(pds_stopped),
        .endpoint_drained(endpoint_drained),""")
    source = source.replace(".src_reset(!por_n_sys)", ".src_reset(!por_n_sys || epoch_reset_sys)")
    source = source.replace(".dst_reset(!por_n_mem)", ".dst_reset(!por_n_mem || epoch_reset_mem)")
    source = replace(source, ".dst_rdata(dst_rdata), .drained()", ".dst_rdata(dst_rdata), .drained(card_cdc_drained)")
    marker = ".clk(clk_mem), .por_n(por_n_mem), .reset_request(1'b0), .drained(),"
    assert source.count(marker) == 2
    source = source.replace(marker, ".clk(clk_mem), .por_n(por_n_mem && !epoch_reset_mem),\n        .reset_request(controller_quiesce), .drained(adapter_drained),", 1)
    source = replace(source, ".clk(clk_mem), .por_n(por_n_mem), .reset_request(1'b0), .drained(),", ".clk(clk_mem), .por_n(por_n_mem && !epoch_reset_mem),\n        .reset_request(controller_quiesce), .drained(mux_drained),")
    source = replace(source, ".src_valid(floppy_req), .src_ready(), .src_write(1'b0), .src_addr(floppy_addr),", ".src_valid(floppy_offer), .src_ready(floppy_ready), .src_write(1'b0), .src_addr(floppy_source_addr),")
    source = replace(source, ".src_rsp_valid(floppy_rsp_valid), .src_rsp_ready(!floppy_req),", ".src_rsp_valid(floppy_source_response), .src_rsp_ready(floppy_source_ready),")
    source = replace(source, ".dst_rdata(floppy_frozen_data), .drained()", ".dst_rdata(floppy_frozen_data), .drained(floppy_cdc_drained)")
    source = replace(source, "    assign floppy_ack = floppy_rsp_valid;\n", "")
    source = replace(source, "wire floppy_dst_valid, floppy_dst_ready, floppy_rsp_valid, floppy_rsp_ready;",
                     "wire floppy_dst_valid, floppy_dst_ready, floppy_rsp_ready;")
    source = replace(source, "        if (!por_n_mem) begin", "        if (!por_n_mem || epoch_reset_mem) begin")
    WORK.mkdir(parents=True, exist_ok=True)
    result = WORK / "card_platform.sv"
    result.write_text(source, encoding="ascii")
    return result


if __name__ == "__main__":
    print(prepare())
