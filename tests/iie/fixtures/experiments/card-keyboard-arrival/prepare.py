#!/usr/bin/env python3
"""Resume the bounded card CPU with a test-only keyboard consumer."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-keyboard-arrival'
PARENT = HERE.parent / 'card-event-backpressure'
spec = importlib.util.spec_from_file_location('recovery_busy_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    base_image = image
    original = bytes(int(value, 16) for value in image.read_text().split())
    payload = ROOT / 'local/experiments/firmware-memory/decoded/Monx_2606.payload.bin'
    offset = 0x20000 + 0xfb65 - 0xc000
    probe = bytes.fromhex('ad00c0 8d0002 8d10c0 ad00c0 8d0102 4c65fb')
    assert original[offset:offset + len(probe)] == payload.read_bytes()[0x3b65:0x3b65 + len(probe)]
    patched = bytearray(original)
    patched[offset:offset + len(probe)] = probe
    image = WORK / 'consumer.hex'
    image.write_text(''.join(f'{value:02x}\n' for value in patched), encoding='ascii')
    overlay = WORK / 'consumer-overlay.json'
    overlay.write_text(json.dumps({'physical_address': offset, 'cpu_address': 0xfb65,
        'original': original[offset:offset + len(probe)].hex(), 'consumer': probe.hex(),
        'firmware_sha256': sha(payload), 'base_image_sha256': sha(base_image),
        'consumer_image_sha256': sha(image)}, indent=2) + '\n', encoding='ascii')
    card_path = WORK / 'card_irq_candidate.sv'
    card = once(card_path.read_text(), '    reg cpu_running,',
                '    reg test_consume = 0, test_ignore_key_clear = 0;\n    reg cpu_running,')
    card = once(card, "cpu_address == 16'hFB65;", "cpu_address == 16'hFB65 && !test_consume;")
    card = once(card, "if (!cpu_write && cpu_address == 16'hC010) keyboard[7] <= 0;",
                "if (cpu_address == 16'hC010 && !test_ignore_key_clear) keyboard[7] <= 0;")
    card = once(card, 'wire allowed_io = service_register ||',
                "wire allowed_io = cpu_address == 16'hC010 || service_register ||")
    card = once(card, 'if (keyboard_write) keyboard <= sidefx_wdata[7:0];',
                "if (keyboard_write) keyboard <= {1'b1, sidefx_wdata[6:0]};")
    card_path.write_text(card, encoding='ascii')
    bench = sources[0]
    text = once(bench.read_text(), 'bridge_index <= 109;', 'bridge_index <= 111;')
    text = once(text, "event_pulses != 0 || dut.platform.card.card.sidefx_wdata[7:0] !== 8'hD5",
                "event_pulses > 2 || dut.platform.card.card.sidefx_wdata[7:0] !== (event_pulses == 0 ? 8'hD5 : event_pulses == 1 ? 8'h41 : 8'h42)")
    text = once(text, '            if (bridge_write && bridge_offset == 24)\n                $fatal(1, "busy keyboard received event write");',
                '''            if (bridge_write && bridge_offset == 24) begin
                event_writes = event_writes + 1;
                if (event_pulses != event_writes + 1 || bridge_value != 64 + event_writes ||
                    dut.platform.card.card.keyboard !== (bridge_value[7:0] | 8'h80))
                    $fatal(1, "recovery keyboard write mismatch");
                $display("EVENT write=%0d keyboard=%h", event_writes, dut.platform.card.card.keyboard);
                consume_key(bridge_value[7:0] | 8'h80);
            end
            if (bridge_index == 70) consume_key(8'hD5);''')
    text = once(text, "event_writes != 0 || event_pulses != 1 || dut.platform.card.card.keyboard !== 8'hD5",
                "event_writes != 2 || event_pulses != 3 || dut.platform.card.card.keyboard !== 8'h42")
    text = once(text, '        $display("BUSY keyboard=d5 pulses=%0d", event_pulses);',
                '        $display("RECOVERY keyboard=42 pulses=%0d", event_pulses);')
    marker = '    integer bridge_reply,'
    text = once(text, marker, '''    integer ignore_key_clear = 0, consumer_reads = 0, consumer_clears = 0;
    reg consumer_active = 0;
    reg [7:0] consumed_key;
    always @(posedge clk_sys) begin
        if (consumer_active && dut.platform.card.card.cpu_ready) begin
            if (card_cpu_address == 16'hC000) begin
                if (dut.platform.card.card.cpu_rdata !== (consumer_reads == 0 || dut.platform.card.card.test_ignore_key_clear ? consumed_key : (consumed_key & 8'h7F)))
                    $fatal(1, "consumer keyboard read mismatch");
                consumer_reads <= consumer_reads + 1;
            end
            if (card_cpu_address == 16'hC010) begin
                if (!dut.platform.card.card.cpu_write) $fatal(1, "consumer clear was not a write");
                consumer_clears <= consumer_clears + 1;
            end
        end
    end
    task consume_key(input [7:0] key);
        begin
            if (!boundary || dut.platform.card.card.processor.cpu.reg_a != saved_a ||
                dut.platform.card.card.processor.cpu.reg_x != saved_x ||
                dut.platform.card.card.processor.cpu.reg_y != saved_y ||
                dut.platform.card.card.processor.cpu.reg_s != saved_s ||
                dut.platform.card.card.processor.cpu.reg_p != saved_p)
                $fatal(1, "consumer entry context mismatch");
            consumer_reads = 0; consumer_clears = 0; consumed_key = key;
            consumer_active = 1;
            dut.platform.card.card.test_ignore_key_clear = ignore_key_clear != 0 && key != 8'hD5;
            dut.platform.card.card.test_consume = 1;
            wait(dut.platform.card.card.cpu_ready && dut.platform.card.card.cpu_sync && card_cpu_address == 16'hFB65);
            @(posedge clk_sys);
            @(negedge clk_sys);
            dut.platform.card.card.test_consume = 0;
            wait(boundary);
            @(negedge clk_sys);
            consumer_active = 0;
            if (consumer_reads != 2 || consumer_clears != 1 || expected['h200] != key ||
                expected['h201] != (dut.platform.card.card.test_ignore_key_clear ? key : (key & 8'h7F)) ||
                dut.platform.card.card.keyboard !== (dut.platform.card.card.test_ignore_key_clear ? key : (key & 8'h7F)) ||
                dut.platform.card.card.processor.cpu.reg_x != saved_x ||
                dut.platform.card.card.processor.cpu.reg_y != saved_y ||
                dut.platform.card.card.processor.cpu.reg_s != saved_s)
                $fatal(1, "consumer result mismatch reads=%0d clears=%0d samples=%h/%h key=%h", consumer_reads,
                    consumer_clears, expected['h200], expected['h201], dut.platform.card.card.keyboard);
            saved_a = dut.platform.card.card.processor.cpu.reg_a;
            saved_p = dut.platform.card.card.processor.cpu.reg_p;
            $fflush(instructions);
            $display("CONSUME before=%h after=%h reads=%0d clears=%0d ignore=%0d",
                key, dut.platform.card.card.keyboard, consumer_reads, consumer_clears,
                dut.platform.card.card.test_ignore_key_clear);
        end
    endtask
''' + marker)
    text = once(text, '        $readmemh(image_path, expected);', '''        if ($value$plusargs("ignore_key_clear=%d", ignore_key_clear)) begin end
        $readmemh(image_path, expected);''')
    bench.write_text(text, encoding='ascii')
    bridge_path = WORK / 'bridge.lua'
    bridge_path.write_text(once(bridge_path.read_text(), 'sequence <= 109', 'sequence <= 111'), encoding='ascii')
    host_path = WORK / 'execute.lua'
    host_path.write_text(once(host_path.read_text(), 'local/experiments/card-event-backpressure/bridge.lua',
                             'local/experiments/card-keyboard-arrival/bridge.lua'), encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', overlay, payload, base_image, image]
