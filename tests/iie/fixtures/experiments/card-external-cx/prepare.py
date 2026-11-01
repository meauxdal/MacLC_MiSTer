#!/usr/bin/env python3
"""Continue the first BS3 mismatch through an external ROM probe."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-external-cx'
PARENT = HERE.parent / 'card-boot-service2'
BASE = HERE.parent / 'card-boot-service3'
spec = importlib.util.spec_from_file_location('external_cx_prepare', BASE / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    fill_pins = HERE.parent / 'card-slot3-recovery/results.json'
    fill_evidence = json.loads(fill_pins.read_text())
    for name, digest in fill_evidence['inputs_sha256'].items():
        assert sha(Path(name)) == digest, name
        inputs.append(Path(name))
    fill = bytes.fromhex('00ea') * (0xC000 // 2)
    assert hashlib.sha256(fill).hexdigest() == fill_evidence['host_initial_fill']['sha256']
    data = bytes(int(value, 16) for value in image.read_text().splitlines())
    assert data[0x2C100:0x2C800] == fill[0x8100:0x8800], 'expected initial external fill'
    card = WORK / 'card_irq_candidate.sv'
    text = once(card.read_text(), '    wire slot3_read =', """    wire external_cx_read = !cpu_write && cpu_address >= 16'hC100 &&
        cpu_address < 16'hC800 && !internal_cx && !FIXED_CX;
    wire slot3_read =""")
    route = "18'h20000 + {2'b0, cpu_address}"
    if os.environ.get('IIE_CX_CONTROL') == '1':
        route = "(slot3_read ? 18'h20000 + {2'b0, cpu_address} : "
        route += "18'h20000 + {2'b0, cpu_address} - 18'h0C000)"
    text = once(text, "slot3_read ? 18'h2C300 + {10'b0, cpu_address[7:0]}",
                'external_cx_read ? ' + route)
    text = once(text, '!io_space && !slot3_read &&', '!io_space && !external_cx_read &&')
    text = once(text, "service_returns == 4 && cpu_valid && cpu_sync && cpu_address == 16'hFAC2;",
                "service_returns == 4 && cpu_valid && cpu_sync && cpu_address == 16'hFAC0;")
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = once(bench.read_text(), '    integer cx_reads =',
                '    integer external_reads = 0;\n    integer cx_reads =')
    text = once(text, '                end else if (!dut.platform.card.card.internal_cx)', """                end else if (dut.platform.card.card.external_cx_read) begin
                    if (card_cpu_address !== 16'hC505 ||
                        dut.platform.card.card.physical !== 18'h2C505 ||
                        dut.platform.card.card.cpu_rdata !== 8'hEA ||
                        expected['h2C505] !== 8'hEA || expected['h20505] !== 8'h38 ||
                        dut.platform.card.card.processor.cpu.reg_y !== 5)
                        $fatal(1, "external Cx routing mismatch address=%h physical=%h data=%h",
                               card_cpu_address, dut.platform.card.card.physical,
                               dut.platform.card.card.cpu_rdata);
                    external_reads = external_reads + 1;
                    $display("EXTERNAL address=%h physical=%h data=%h", card_cpu_address,
                             dut.platform.card.card.physical, dut.platform.card.card.cpu_rdata);
                end else if (!dut.platform.card.card.internal_cx)""")
    text = once(text, "card_cpu_address !== 16'hFAC2 || opcodes != 4", "card_cpu_address !== 16'hFAC0 || opcodes != 4")
    text = text.replace("8'(boot_a - 1)", "8'(boot_a - 2)")
    text = once(text, '        for (i = 1; i <= 9; i = i + 1)', """        if (external_reads != 1 || expected['h7F8] !== 8'hC5 ||
            expected[1] !== 8'hC4 ||
            dut.platform.card.card.processor.cpu.reg_a !== 8'hC4)
            $fatal(1, "external Cx scan did not reach matching BS3 request");
        $display("SCAN next_A=%h next_PC=%h external_reads=%0d",
                 dut.platform.card.card.processor.cpu.reg_a, card_cpu_address, external_reads);
        for (i = 1; i <= 9; i = i + 1)""")
    text = once(text, 'PASS boot-service3 fast=', 'PASS external-cx fast=')
    bench.write_text(text, encoding='ascii')
    host = WORK / 'host.lua'
    host.write_text((BASE / 'host.lua').read_text(), encoding='ascii')
    return sources, image, inputs + [fill_pins, BASE / 'prepare.py', BASE / 'host.lua', HERE / 'prepare.py', host]
