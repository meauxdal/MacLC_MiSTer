#!/usr/bin/env python3
"""Continue original Applesoft cold start through idle keyboard polling."""
import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-monitor-prompt'
POST = HERE.parent / 'card-monitor-post-match'
BASE = HERE.parent / 'card-boot-service3'
MATCH = HERE.parent / 'card-boot-service3-live-match'
PARENT = HERE.parent / 'card-boot-service2'
spec = importlib.util.spec_from_file_location('prompt_prepare', POST / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    os.environ['IIE_FINISH_INIT'] = '1'
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    card = WORK / 'card_irq_candidate.sv'
    candidate = once(card.read_text(), "cpu_address == 16'hF1D2;", "cpu_address == 16'hC27D && idle_reads == 260;")
    candidate = once(candidate,
        '    reg [7:0] sizing_page;', '''    reg [7:0] sizing_page;
    reg input_started;
    integer idle_reads;
    always @(posedge clk) begin
        if (!por_n || !cpu_running) begin input_started <= 0; idle_reads <= 0; end
        else begin
            if (cpu_valid && cpu_sync && cpu_address == 16'hC267) input_started <= 1;
            if (input_started && cpu_ready && !cpu_write && cpu_address == 16'hC000)
                idle_reads <= idle_reads + 1;
        end
    end''')
    candidate = once(candidate, 'wire protected_write = firmware_test', '''wire protected_write =
        ($test$plusargs("drop_prompt") && service_returns == 5 && cpu_write && cpu_address == 16'h0500) ||
        ($test$plusargs("drop_seed") && input_started && cpu_write && cpu_address == 16'h004F) ||
        firmware_test''')
    card.write_text(candidate, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    start = text.index('        if (external_reads != 1 ||')
    end = text.index('        $display("EXCHANGE writes=', start)
    cold = text[start:end]
    text = text[:start] + '        check_idle();\n' + text[end:]
    text = once(text, '    integer cold_entries =', '''    reg cold_checked = 0;
    task check_cold;
        begin
''' + cold + '''        end
    endtask
    always @(posedge clk_sys) begin
        if (!cold_checked && cpu_valid && dut.platform.card.card.cpu_sync &&
            dut.platform.card.card.service_returns == 5 && card_cpu_address == 16'hF1D2) begin
            check_cold();
            if (expected['h24] !== 0 || expected['h25] !== 1 ||
                expected['h28] !== 8'h80 || expected['h29] !== 4)
                $fatal(1, "cold cursor checkpoint mismatch");
            for (integer byte_index = 0; byte_index < 1024; byte_index = byte_index + 1) begin
                cold_text[byte_index] = expected['h400 + byte_index];
                cold_aux[byte_index] = expected['h10400 + byte_index];
            end
            cold_checked = 1;
        end
    end
    integer cold_entries =''')
    text = once(text, "card_cpu_address !== 16'hF1D2 || opcodes", "card_cpu_address !== 16'hC27D || opcodes")
    text = once(text, '    reg cold_checked = 0;', '''    integer prompt_writes = 0;
    reg [7:0] cold_text [0:1023], cold_aux [0:1023];
    reg input_seen = 0;
    reg [15:0] input_seed;
    always @(posedge clk_sys) begin
        if (cold_checked && cpu_ready && dut.platform.card.card.cpu_write &&
            card_cpu_address >= 16'h0400 && card_cpu_address < 16'h0800) begin
            prompt_writes = prompt_writes + 1;
            $display("PROMPT_WRITE address=%h data=%h", card_cpu_address, dut.platform.card.card.cpu_wdata);
        end
        if (cpu_valid && dut.platform.card.card.cpu_sync && card_cpu_address == 16'hC267 && !input_seen) begin
            input_seen = 1;
            input_seed = {expected['h4F], expected['h4E]};
            if (backing('h500) !== 8'hDD)
                $fatal(1, "prompt store missing before input");
            if (input_seed !== 0 || expected['h24] !== 1 || expected['h25] !== 2 ||
                expected['h28] !== 0 || expected['h29] !== 5 || backing('h501) !== 8'h60)
                $fatal(1, "prompt input-entry checkpoint mismatch");
            $display("INPUT_ENTRY seed=%h cursor=%h row=%h base=%h%h vectors=%h%h/%h%h",
                     input_seed, expected['h24], expected['h25], expected['h29], expected['h28],
                     expected['h37], expected['h36], expected['h39], expected['h38]);
        end
        if (dut.platform.card.card.input_started && cpu_ready && !dut.platform.card.card.cpu_write &&
            card_cpu_address == 16'hC000 && dut.platform.card.card.cpu_rdata !== 0)
            $fatal(1, "idle keyboard read did not preserve empty latch");
    end
    reg cold_checked = 0;''')
    text = once(text, '    integer prompt_writes = 0;', (HERE / 'idle.sv').read_text() + '\n    integer prompt_writes = 0;')
    text = once(text, 'PASS post-match fast=', 'PASS prompt fast=')
    bench.write_text(text, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'checks.py', HERE / 'idle.sv',
                                     HERE / 'verify.py', POST / 'run.py']
