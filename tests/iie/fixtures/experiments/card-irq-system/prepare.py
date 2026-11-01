#!/usr/bin/env python3
"""Generate an isolated, source-pinned IRQ variant of self-authored harness RTL."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[3]
PINS = {
    "fixtures/experiments/card-system-harness/card_candidate.sv": "25e2c13685ebda3e3957c5ab029f482ccbd32fa66949ebc1cffaa4038ff4c3a8",
    "fixtures/experiments/card-host-rtl/card_host_registers.sv": "204e10d22a5a38f9032a4c3459d0170e4ddb113aaa8d96f386fa1ae1cc3bf2b2",
    "fixtures/experiments/card-cpu-rtl/card_cpu_bus.sv": "ad5795f1c58e765e7d4e773f3841c56ab8f41a540ae7b497705f24ceb00fe8cc",
}


def replace(code, old, new):
    assert code.count(old) == 1, old
    return code.replace(old, new, 1)


def generate(work):
    code = {}
    for name, expected in PINS.items():
        path = ROOT / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
        code[path.stem] = path.read_text(encoding="utf-8")
    cpu = replace(code["card_cpu_bus"], "module card_cpu_bus (", "module card_irq_cpu_bus (")
    cpu = replace(cpu, "    output wire vector_pull,", "    output wire vector_pull,\n    output wire rti_done,")
    cpu = replace(cpu, ".rti_done(),", ".rti_done(rti_done),")
    host = replace(code["card_host_registers"], "module card_host_registers (", "module card_irq_host_registers (")
    host = replace(host, "    reg word_access,", "    reg [7:0] command_byte;\n    reg word_access,")
    host = replace(host, "            control <= 0;", "            control <= 0;\n            command_byte <= 0;")
    host = replace(host, "                                {1'b0, 6'h0D}: control <= req_wdata[7:0];",
                   "                                {1'b0, 6'h20}: command_byte <= req_wdata[7:0];\n"
                   "                                {1'b1, 6'h20}: command_byte <= req_wdata[15:8];\n"
                   "                                {1'b0, 6'h0D}: control <= req_wdata[7:0];")
    host = replace(host, "                                {1'b0, 6'h20}, {1'b1, 6'h20}, {1'b0, 6'h21}: ;",
                   "                                {1'b0, 6'h21}: ;")
    host = replace(host, "                                {1'b0, 6'h0D}: rsp_rdata <= {8'b0, control};",
                   "                                {1'b0, 6'h20}: rsp_rdata <= {8'b0, command_byte};\n"
                   "                                {1'b0, 6'h0D}: rsp_rdata <= {8'b0, control};")
    card = replace(code["card_candidate"], "module card_candidate (",
                   "module card_irq_candidate #(parameter SUPPRESS_NMI = 0, SUPPRESS_IRQ = 0,\n"
                   "                            NMI_DELAY = 0, IRQ_DELAY = 0) (")
    card = replace(card, "    reg cpu_running,", "    reg nmi_pending, nmi_overlay, irq_level;\n"
                   "    reg [31:0] nmi_delay_left, irq_delay_left;\n    wire rti_done;\n    reg cpu_running,")
    card = replace(card, "    wire [17:0] physical = cpu_address >= 16'hFFFA",
                   "    wire firmware_read = nmi_overlay && !cpu_write &&\n"
                   "                         ((cpu_address >= 16'hD000 && cpu_address < 16'hD006) ||\n"
                   "                          (cpu_address == 16'hD006 && !cpu_sync));\n"
                   "    wire [17:0] physical = firmware_read ? 18'h25000 + {2'b0, cpu_address} - 18'h0D000 :\n"
                   "        cpu_address >= 16'hFFFA")
    card = replace(card, "                           (!io_space && cpu_address >= 16'hC000 &&",
                   "                           (!io_space && !firmware_read && cpu_address >= 16'hC000 &&")
    card = replace(card, "cpu_address == 16'h202F;", "cpu_address == 16'h203A;")
    card = replace(card, "    card_host_registers host (", "    card_irq_host_registers host (")
    card = replace(card, "    card_cpu_bus processor (", "    card_irq_cpu_bus processor (")
    card = replace(card, "        .irq_n(1'b1), .nmi_n(1'b1),", "        .irq_n(candidate_irq_n), .nmi_n(candidate_nmi_n),")
    card = replace(card, ".vector_pull(vector_pull), .halted(cpu_halted),",
                   ".vector_pull(vector_pull), .rti_done(rti_done), .halted(cpu_halted),")
    card = replace(card, "    always @* begin\n        cpu_rdata", "    wire opcode02_complete = runnable && cpu_sync && !cpu_write &&\n"
                   "                             cpu_memory_wait && master_rsp_valid[1] && cpu_rdata == 8'h02;\n"
                   "    wire candidate_nmi_n = SUPPRESS_NMI ||\n"
                   "        !((nmi_pending && nmi_delay_left == 0) || (opcode02_complete && NMI_DELAY == 0));\n"
                   "    wire candidate_irq_n = SUPPRESS_IRQ || !(irq_level && irq_delay_left == 0);\n\n"
                   "    always @* begin\n        cpu_rdata")
    card = replace(card, "\n            cpu_running <= 0;", "\n            nmi_pending <= 0;\n            nmi_overlay <= 0;\n"
                   "            irq_level <= 0;\n            nmi_delay_left <= 0;\n            irq_delay_left <= 0;\n"
                   "            cpu_running <= 0;")
    card = replace(card, "        end else begin\n            if (req_valid && req_ready)",
                   "        end else begin\n"
                   "            if (nmi_delay_left != 0) nmi_delay_left <= nmi_delay_left - 1;\n"
                   "            if (irq_delay_left != 0) irq_delay_left <= irq_delay_left - 1;\n"
                   "            if (opcode02_complete) begin\n"
                   "                nmi_pending <= 1;\n                nmi_delay_left <= NMI_DELAY;\n            end\n"
                   "            if (cpu_ready && vector_pull && cpu_address == 16'hFFFA) begin\n"
                   "                nmi_pending <= 0;\n                nmi_overlay <= 1;\n            end\n"
                   "            if (cpu_ready && rti_done) nmi_overlay <= 0;\n"
                   "            if (req_valid && req_ready)")
    card = replace(card, "\n                        cpu_running <= 0;", "\n                        nmi_pending <= 0;\n"
                   "                        nmi_overlay <= 0;\n                        irq_level <= 0;\n"
                   "                        nmi_delay_left <= 0;\n                        irq_delay_left <= 0;\n"
                   "                        cpu_running <= 0;")
    card = replace(card, "!sidefx_word && sidefx_wdata[7:0] == 8'h88",
                   "!sidefx_word && (sidefx_wdata[7:0] & 8'hDF) == 8'h88")
    card = replace(card, "                        armed <= 1;\n                        report_mode <= 0;",
                   "                        armed <= 1;\n                        report_mode <= 0;\n"
                   "                        irq_level <= sidefx_wdata[5];\n"
                   "                        if (sidefx_wdata[5] && !irq_level) irq_delay_left <= IRQ_DELAY;")
    work.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, content in (("card_irq_cpu_bus.sv", cpu), ("card_irq_host_registers.sv", host), ("card_irq_candidate.sv", card)):
        path = work / name
        path.write_text(content, encoding="ascii", newline="\n")
        outputs.append(path)
    return outputs
