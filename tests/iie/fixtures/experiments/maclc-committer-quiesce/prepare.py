#!/usr/bin/env python3
"""Extract a pinned committer and add isolated transport/drain hooks."""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "local/experiments/maclc-committer-quiesce"
SOURCE = Path("C:/Workspace/Git/MacLC_MiSTer/rtl/floppy_sd.v")
PIN = "511ab0548c7f4f2d712bdc737b6442b006264ecaca75f01a5383ce3fa0424988"


def prepare():
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PIN
    source = raw.decode("utf-8")
    start = source.index("module floppy_write_committer")
    source = source[start:source.index("endmodule", start) + len("endmodule")]
    source = source.replace("\r\n", "\n")
    # The source comment contains Unicode; generated candidate comments are ASCII.
    source = source.encode("ascii", errors="replace").decode("ascii")
    baseline = source
    source = source.replace("\tinput             clk,", "\tinput             upstream_stopped,\n\toutput            stopped,\n\tinput             clk,", 1)
    source = source.replace("DONE_PULSE = 3'd5;", "DONE_PULSE = 3'd5,\n\t           ACK_LOW    = 3'd6;")
    source = source.replace("\tassign busy", "\t// Upstream must retain buffer ownership and stop new sector offers.\n\tassign stopped = upstream_stopped && !rst && !sector_valid &&\n\t                 !busy && !done && !wr_req && !wr_ack;\n\n\tassign busy", 1)
    old = """\t\t\t\tif (word_idx == 8'd255)
\t\t\t\t\tstate <= DONE_PULSE;
\t\t\t\telse begin
\t\t\t\t\tword_idx <= word_idx + 8'd1;
\t\t\t\t\tstate    <= FETCH_LO;
\t\t\t\tend"""
    assert source.count(old) == 1
    source = source.replace(old, "\t\t\t\tstate <= ACK_LOW;")
    source = source.replace("\t\t\tDONE_PULSE: begin", "\t\t\tACK_LOW: if (!wr_ack) begin\n" + old + "\n\t\t\tend\n\n\t\t\tDONE_PULSE: begin")
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "committer_baseline.v").write_text(baseline + "\n", encoding="ascii")
    (WORK / "committer_candidate.v").write_text(source + "\n", encoding="ascii")
    return source


if __name__ == "__main__":
    prepare()
