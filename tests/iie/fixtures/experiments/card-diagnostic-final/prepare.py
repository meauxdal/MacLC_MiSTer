#!/usr/bin/env python3
"""Compose the bounded overlay candidate with the IWM register front end."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'local/experiments/card-firmware-overlay'
WORK = ROOT / 'local/experiments/card-diagnostic-final'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    generator = ROOT / 'fixtures/experiments/card-firmware-overlay/prepare.py'
    manifest = json.loads((generator.parent / 'results.json').read_text())
    assert sha(generator) == manifest['inputs_sha256'][str(generator)]
    spec = importlib.util.spec_from_file_location('final_overlay', generator)
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    overlay.WORK = WORK
    closure = overlay.prepare()
    card = WORK / 'card_irq_candidate.sv'
    assert sha(card) == manifest['inputs_sha256'][str(BASE / card.name)]
    text = once(card.read_text(), "cpu_address == 16'h204F;", "cpu_address == 16'h2055;")
    text = once(text, '    wire cpu_ready;', '''    wire cpu_ready;
    wire iwm_selected = cpu_address[15:4] == 12'hC0E;
    wire [7:0] iwm_rdata;
    wire [4:0] iwm_mode;
    wire iwm_motor, iwm_q6, iwm_q7;
    card_iwm_frontend iwm (
        .clk(clk), .reset(!por_n || !cpu_running), .complete(cpu_ready),
        .selected(iwm_selected), .address(cpu_address[3:0]), .write(cpu_write),
        .write_data(cpu_wdata), .drive_data(8'hFF), .drive_sense(1'b1),
        .write_busy(1'b0), .write_underrun(1'b0), .read_data(iwm_rdata),
        .phases(), .motor(iwm_motor), .drive_select(), .q6(iwm_q6), .q7(iwm_q7),
        .mode(iwm_mode), .data_read(), .data_write(), .data_out()
    );''')
    text = once(text, 'wire allowed_io = io_trap ||', 'wire allowed_io = iwm_selected || io_trap ||')
    text = once(text, '            default: ;\n        endcase\n    end\n\n    always @(posedge clk)',
                '            default: if (iwm_selected) cpu_rdata = iwm_rdata;\n'
                '        endcase\n    end\n\n    always @(posedge clk)')
    card.write_text(text, encoding='ascii')
    frontend = ROOT / 'fixtures/experiments/card-iwm/card_iwm_frontend.sv'
    iwm_manifest = json.loads((frontend.parent / 'results.json').read_text())
    assert sha(frontend) == iwm_manifest['inputs_sha256'][str(frontend)]
    closure.append(frontend)
    return closure
