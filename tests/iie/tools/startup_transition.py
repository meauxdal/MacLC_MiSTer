#!/usr/bin/env python3
"""Connect existing Conf and monitor fixtures without resetting card state."""
from pathlib import Path

from prepare_runtime import ROOT


def prepare_host(rom, program):
    conf = ROOT / 'local/experiments/firmware-memory/code/Conf_1000.bin'
    data = conf.read_bytes()
    assert len(data) < 0x1000
    rom[0x2000:0x2000 + len(data)] = data
    rom[:8] = bytes.fromhex('0000ffbc00000100')
    rom[0x100:0x10c] = bytes.fromhex('287cfee000004ef900002046')
    # Match the saved A4 consumed by the reset tail's epilogue.
    rom[0x180:0x188] = bytes.fromhex('2f0c4ef9002004ca')
    # Saved Conf registers, Pascal return address and result slot.
    rom[0xffbc:0xffec] = bytes(0x30)
    rom[0xffe0:0xffe4] = bytes.fromhex('00000300')
    rom[0xffe8:0xffea] = bytes.fromhex('ffff')
    start = program.index(bytes.fromhex('137c0003000d337c08020020'))
    program = program[:start] + bytes.fromhex(
        '46fc27002a7c00300000287cfee000002b4cedca'
        '4eb9002002a24eb9000001804ef90020281c')
    program = bytes.fromhex('30390000ffe833c000008004') + program
    assert 0x300 + len(program) < 0x1000
    rom[0x300:0x300 + len(program)] = program
    return rom, [conf, Path(__file__)]


def prepare_card(image):
    initial = ROOT / 'local/experiments/card-diagnostic-final/expected0.hex'
    payload = ROOT / 'local/experiments/firmware-memory/decoded/Conf_1001.payload.bin'
    diagnostic = bytearray.fromhex(initial.read_text())
    image[:0x20000] = bytes(0x20000)
    for start, end in ((0x23ffa, 0x24000), (0x25000, 0x27000), (0x2fffa, 0x30000)):
        image[start:end] = diagnostic[start:end]
    code = payload.read_bytes()
    for base in (0x2000, 0x12000):
        image[base:base + len(code)] = code
    return image, [initial, payload]


def prepare_bench(bench, prefix=False, render=False):
    bench = bench.replace('reg reset_entry_seen = 0;', '''reg reset_entry_seen = 0, conf_done = 0;
    reg diagnostic_seen = 0, runtime_seen = 0, cleanup_seen = 0;
    integer capture_base = 0;
    reg transition_hole_seen = 0, transition_next_seen = 0;''')
    bench = bench.replace('if (card.card.cpu_ready && card.card.cpu_sync && !reset_entry_seen)',
                          'if (conf_done && card.card.cpu_ready && card.card.cpu_sync && !reset_entry_seen)')
    bench = bench.replace('if (card.card.opcode02_complete) begin',
                          'if (conf_done && card.card.opcode02_complete) begin')
    bench = bench.replace('if (card.card.cpu_ready && card.card.rti_done)',
                          'if (conf_done && card.card.cpu_ready && card.card.rti_done)')
    bench = bench.replace("rw_n && capture_address == 16'hC07D && !service_ack)",
                          "rw_n && conf_done && capture_address == 16'hC07D && !service_ack)")
    bench = bench.replace('captures != 16', 'captures - capture_base != 16')
    bench = bench.replace('ticks > 100000)', 'ticks > 2000000)')
    bench = bench.replace('    always @(posedge clk) begin', '''    always @(posedge clk) begin
        if (card.card.cpu_running && !conf_done) begin
            if (card.card.monitor_active) $fatal(1, "Conf selected runtime mapping");
            diagnostic_seen <= 1;
        end
        if (conf_done && card.card.cpu_running) begin
            if (!card.card.monitor_active) $fatal(1, "runtime start retained diagnostic mapping");
            runtime_seen <= 1;
        end
        if (!conf_done && diagnostic_seen && !card.card.cpu_running &&
            !card.card.reset_pending && card.card.drained && !capture_valid)
            cleanup_seen <= 1;
        if (!as_n && !rw_n && address == 32'h8004 && !conf_done) begin
            if (data_out != 0 || !diagnostic_seen || !cleanup_seen || captures != 63 ||
                card.card.cpu_running || capture_valid || card.card.reset_pending)
                $fatal(1, "Conf transition cleanup mismatch result=%h captures=%0d", data_out, captures);
            conf_done <= 1;
            capture_base <= captures;
            $display("PHASE Conf cleanup complete captures=%0d", captures);
        end''', 1)
    bench = bench.replace('if (!driver_return || rti_count',
                          'if (!conf_done || !runtime_seen || !driver_return || rti_count')
    bench = bench.replace('continuation mismatch latch=%h',
                          'continuation mismatch conf=%b runtime=%b latch=%h')
    bench = bench.replace("world[16'hF770 >> 1][7:0], rti_count, driver_return, service_reads,",
                          "conf_done, runtime_seen, world[16'hF770 >> 1][7:0], rti_count, driver_return, service_reads,")
    bench = bench.replace('PASS original TG68K upload and driver service 1 ACK/return; card RTI to FBDF',
                          'PASS consecutive Conf cleanup, upload, original reset helpers and service 1 RTI; automatic mapping')
    if prefix:
        marker = "            if (service_ack && card.card.cpu_ready && card.card.cpu_sync && card_cpu == 16\'hFBDF) begin"
        assert marker in bench
        bench = bench.replace(marker, '''            if (conf_done && card.card.cpu_ready && card.card.cpu_write &&
                card_cpu == 16'h05FB && !transition_hole_seen) begin
                if (!runtime_seen || !reset_entry_seen || capture_valid ||
                    uploads != 2 || stream_reads != 108 || stream_writes != 108 ||
                    service_read || service_ack || rti_count != 0 || card.card.cpu_wdata != 0 ||
                    memory[17'h002FD][15:8] != 0)
                    $fatal(1, "transition screen-hole commit mismatch");
                transition_hole_seen <= 1;
            end
            if (transition_hole_seen && !transition_next_seen && capture_valid) begin
                if (capture_address != 16'hC00E || capture_status != 8'hE0 ||
                    capture_data != 8'h89 || captures - capture_base != 5)
                    $fatal(1, "transition next capture mismatch address=%h status=%h data=%h",
                        capture_address, capture_status, capture_data);
                transition_next_seen <= 1;
                $display("PASS consecutive Conf cleanup, upload and reset; monitor screen-hole commit and next C00E capture");
                TRANSITION_PREFIX_FINISH
            end
''' + marker)
        bench = bench.replace('TRANSITION_PREFIX_FINISH', '' if render else '$finish;')
    bench = bench.replace('"driver timeout host=%h', '"driver timeout conf=%b runtime=%b uploads=%0d captures=%0d host=%h')
    bench = bench.replace('address, card_cpu, capture_address, capture_status, service_ack, driver_return, rti_count);',
                          'conf_done, runtime_seen, uploads, captures, address, card_cpu, capture_address, capture_status, service_ack, driver_return, rti_count);')
    marker = '        repeat (10) @(negedge clk);'
    # Three writable buffers consumed by original $26A via $2A2.
    bench = bench.replace(marker, '''        {world[16'hEDD6 >> 1], world[16'hEDD8 >> 1]} = 32'h002F8000;
        {world[16'hEDDA >> 1], world[16'hEDDC >> 1]} = 32'h002F4000;
        {world[16'hEDDE >> 1], world[16'hEDE0 >> 1]} = 32'h002F0000;
''' + marker)
    return bench
