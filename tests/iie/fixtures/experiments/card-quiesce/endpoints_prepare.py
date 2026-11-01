#!/usr/bin/env python3
"""Source-pinned stop/drain hooks for isolated card endpoint experiments."""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/card-quiesce/endpoints"
PINS = {
    "card-system-harness/card_candidate.sv":
        "25e2c13685ebda3e3957c5ab029f482ccbd32fa66949ebc1cffaa4038ff4c3a8",
    "card-pds-harness/card_pds_adapter.sv":
        "e8b54017d1dfc1c9ed70357846ee69bd7e4a2de9c42e0ba2219192b3992a884c",
    "card-pds-system-harness/card_pds_candidate.sv":
        "30f823ebbac4f4125e4bfa534edf85190962df1c80b010a32911443c21be5ee3",
}


def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


def candidate(source):
    source = replace(source, "    input wire por_n,", """    input wire por_n,
    input wire stop_request,
    output wire stopped,
    output wire endpoint_drained,""")
    source = replace(source, "    reg cpu_memory_wait;", """    reg cpu_memory_wait;
    reg cpu_offer_valid;
    reg [17:0] cpu_offer_addr;
    reg cpu_offer_write;
    reg [7:0] cpu_offer_wdata;
    reg host_pending;""")
    source = replace(source,
        "    assign master_valid[1] = runnable && released && !io_space && !cpu_memory_wait;\n"
        "    assign master_write[1] = cpu_write;",
        """    assign stopped = stop_request && !cpu_offer_valid && !cpu_memory_wait;
    assign endpoint_drained = drained && !req_valid && !host_pending && !rsp_valid &&
                              !cpu_offer_valid && !cpu_memory_wait;
    assign master_valid[1] = cpu_offer_valid;
    assign master_write[1] = cpu_offer_write;""")
    source = replace(source,
        "    assign cpu_ready = runnable && released &&\n"
        "                       (io_space ? allowed_io : (cpu_memory_wait && master_rsp_valid[1]));",
        """    assign cpu_ready = (cpu_memory_wait && master_rsp_valid[1]) ||
                       (!stop_request && runnable && released && io_space && allowed_io);""")
    source = replace(source, ".host_addr(host_addr), .card_addr(physical)",
                     ".host_addr(host_addr), .card_addr(cpu_offer_addr)")
    source = replace(source, ".card_wdata({cpu_wdata, cpu_wdata})",
                     ".card_wdata({cpu_offer_wdata, cpu_offer_wdata})")
    source = replace(source, ".card_be(physical[0] ? 2'b10 : 2'b01)",
                     ".card_be(cpu_offer_addr[0] ? 2'b10 : 2'b01)")
    source = replace(source,
        "        cpu_rdata = physical[0] ? master_rdata[15:8] : master_rdata[7:0];",
        "        cpu_rdata = cpu_offer_addr[0] ? master_rdata[15:8] : master_rdata[7:0];")
    source = replace(source, "            cpu_memory_wait <= 0;\n            cpu_completed <= 0;",
        """            cpu_memory_wait <= 0;
            cpu_offer_valid <= 0;
            cpu_offer_addr <= 0;
            cpu_offer_write <= 0;
            cpu_offer_wdata <= 0;
            host_pending <= 0;
            cpu_completed <= 0;""")
    source = replace(source,
        "            if (master_valid[1] && master_ready[1]) cpu_memory_wait <= 1;",
        """            if (req_valid && req_ready) host_pending <= 1;
            if (rsp_valid && rsp_ready) host_pending <= 0;
            if (!stop_request && runnable && released && !io_space &&
                !cpu_memory_wait && !cpu_offer_valid) begin
                cpu_offer_valid <= 1;
                cpu_offer_addr <= physical;
                cpu_offer_write <= cpu_write;
                cpu_offer_wdata <= cpu_wdata;
            end
            if (master_valid[1] && master_ready[1]) begin
                cpu_offer_valid <= 0;
                cpu_memory_wait <= 1;
            end""")
    source = replace(source, "if (start_pending && drained && !cpu_memory_wait)",
                     "if (!stop_request && start_pending && drained && !cpu_memory_wait && !cpu_offer_valid)")
    source = replace(source, "if (runnable && trap && !permitted && !capture_valid)",
                     "if (!stop_request && runnable && trap && !permitted && !capture_valid)")
    source = replace(source, "if (!drained || cpu_memory_wait) fault <= 1;",
                     "if (!drained || cpu_memory_wait || cpu_offer_valid) fault <= 1;")
    return source


def pds_adapter(source):
    source = replace(source, "    input wire reset,", """    input wire reset,
    input wire stop_request,
    output wire stopped,""")
    source = replace(source, "    assign claim =", """    assign stopped = stop_request && (state == IDLE || state == BLOCK);
    assign claim =""")
    source = replace(source, "RESPONSE = 3'd3, DONE = 3'd4;",
                     "RESPONSE = 3'd3, DONE = 3'd4, CLAIM = 3'd5;")
    source = replace(source, "state == REQUEST || state == RESPONSE || state == DONE",
                     "state == CLAIM || state == REQUEST || state == RESPONSE || state == DONE")
    source = replace(source, "((state == IDLE && target) || active)",
                     "((state == IDLE && target && !stop_request) || active)")
    source = replace(source, "else if (!cpu_as_n && strobed) begin",
                     "else if (!stop_request && !cpu_as_n && strobed) begin")
    start = source.index("                        req_offset <=")
    end = source.index("                        state <= REQUEST;", start) + len("                        state <= REQUEST;")
    capture = source[start:end]
    source = replace(source, "            REQUEST: begin", """            CLAIM: begin
                if (reset)
                    state <= BLOCK;
                else if (cpu_as_n)
                    state <= IDLE;
                else if (strobed) begin
""" + capture + """
                end
            end
            REQUEST: begin""")
    source = replace(source, "else if (!stop_request && !cpu_as_n && strobed) begin",
                     """else if (!stop_request && !cpu_as_n && target && !strobed)
                    state <= CLAIM;
                else if (!stop_request && !cpu_as_n && strobed) begin""")
    return source


def pds_candidate(source):
    source = replace(source, "    input wire host_reset,", """    input wire host_reset,
    input wire stop_request,
    output wire cpu_stopped,
    output wire pds_stopped,
    output wire endpoint_drained,""")
    source = replace(source, "        .clk(clk), .reset(host_reset || !por_n),",
        """        .stop_request(stop_request), .stopped(pds_stopped),
        .clk(clk), .reset(host_reset || !por_n),""")
    source = replace(source, "        .clk(clk), .por_n(por_n),",
        """        .stop_request(stop_request && pds_stopped), .stopped(cpu_stopped),
        .endpoint_drained(endpoint_drained),
        .clk(clk), .por_n(por_n),""")
    return source


def prepare():
    transforms = [candidate, pds_adapter, pds_candidate]
    outputs = []
    WORK.mkdir(parents=True, exist_ok=True)
    for (relative, pin), transform in zip(PINS.items(), transforms):
        original = (HERE.parent / relative).read_bytes()
        assert hashlib.sha256(original).hexdigest() == pin, relative
        proposed = transform(original.decode("ascii").replace("\r\n", "\n"))
        output = WORK / Path(relative).name
        output.write_bytes(proposed.encode("ascii"))
        outputs.append(output)
    return outputs


def main():
    prepare()
    print("PASS source-pinned card endpoint stop/drain hooks prepared")


if __name__ == "__main__":
    main()
