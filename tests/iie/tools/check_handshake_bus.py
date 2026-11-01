#!/usr/bin/env python3
"""Run original Conf handshakes on TG68K and the runtime card."""
import argparse
import json
from pathlib import Path

from prepare_runtime import ROOT, MACLC, WORK, RTL, runtime_sources, sha
from check_runtime import linux, run, run_process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--control', action='store_true')
    mode.add_argument('--idle-control', action='store_true',
                      help='Restore rejection of uncaptured running data reads')
    mode.add_argument('--cleanup-error', action='store_true',
                      help='Seed auxiliary RAM to trigger original Conf error 13')
    parser.add_argument('--diagnostic', action='store_true',
                        help='Continue original Conf checks to the diagnostic return')
    parser.add_argument('--cleanup', action='store_true',
                        help='Execute original Conf cleanup and Pascal return')
    args = parser.parse_args()
    args.diagnostic |= args.cleanup
    if args.idle_control and not args.diagnostic:
        parser.error('--idle-control requires --diagnostic')
    if args.cleanup_error and not args.cleanup:
        parser.error('--cleanup-error requires --cleanup')
    closure = runtime_sources()
    if args.control:
        registers = RTL / 'card_irq_host_registers.sv'
        old = WORK / 'handshake-control-registers.sv'
        source = registers.read_text()
        source = source.replace("                                {1'b0, 6'h19}: rsp_rdata <= 0;\n", '')
        old.write_text(source, encoding='ascii')
        closure = [old if p == registers else p for p in closure]
    if args.idle_control:
        candidate = RTL / 'card_irq_candidate.sv'
        old = WORK / 'handshake-control-candidate.sv'
        source = candidate.read_text().replace('    assign rsp_error = host_error;', '''    reg service_error;
    assign rsp_error = host_error || service_error;
    always @(posedge clk) begin
        if (!por_n) service_error <= 0;
        else if (req_valid && req_ready)
            service_error <= !req_write && !req_word && req_offset == 6'h0C &&
                             (cpu_running && !capture_valid && !runtime_refresh);
    end''')
        old.write_text(source, encoding='ascii')
        closure = [old if p == candidate else p for p in closure]
    conf = ROOT / 'local/experiments/firmware-memory/code/Conf_1000.bin'
    rom = bytearray(bytes.fromhex('4e71') * 4096)
    rom[:8] = bytes.fromhex('0000ffbc00000100' if args.cleanup else '0001000000000100')
    rom[0x100:0x10c] = bytes.fromhex('287cfee000004ef900001046')
    original = conf.read_bytes()
    rom[0x1000:0x1000 + len(original)] = original
    stop = 0x1100 if args.diagnostic else 0x1080
    if args.cleanup:
        rom[0x200:0x20e] = bytes.fromhex('30390000ffe833c00000800060fe')
    else:
        rom[stop:stop + 8] = bytes.fromhex('33c00000800060fe')
    image = WORK / 'handshake-host.hex'
    image.write_text(''.join(f'{int.from_bytes(rom[i:i+2], "big"):04x}\n'
                            for i in range(0, len(rom), 2)), encoding='ascii')
    bench = (ROOT / 'fixtures/experiments/maclc-iie-trial/tb_launch_bus.sv').read_text()
    bench = bench.replace('.por_n(!reset),', ".por_n(!reset), .runtime_mode(1'b0),")
    bench = bench.replace('reg [15:0] rom [0:255];', '''reg [15:0] rom [0:4095];
    reg [15:0] stack [0:32767];
    reg [7:0] initial_card [0:262143];
    reg [15:0] memory [0:131071];
    reg [15:0] memory_response = 0;
    reg release_seen = 0, release_read_seen = 0;
    reg idle_read_seen = 0;
    reg late_capture_seen = 0, cleanup_reset_seen = 0;
    always @(posedge clk) begin
        if (!as_n && !rw_n && address[31:16] == 0 && address >= 32'h8000) begin
            if (!uds_n) stack[address[15:1]][15:8] <= data_out[15:8];
            if (!lds_n) stack[address[15:1]][7:0] <= data_out[7:0];
        end
        if (mem_valid && !mem_rsp_valid) begin
            if (mem_write) memory[mem_addr] <= mem_data;
            memory_response <= memory[mem_addr];
        end
        if (card.card.read_release) release_seen <= 1;
        if (card.req_valid && card.req_ready && !card.req_write && !card.req_word &&
            card.req_offset == 6'h0C && card.card.cpu_running && !capture_valid)
            idle_read_seen <= 1;
        if (capture_valid && captures == 63 && capture_status == 8'h28 &&
            capture_address == 16'hC0E8) late_capture_seen <= 1;
        if (card.req_valid && card.req_ready && card.req_write &&
            card.req_word && card.req_offset == 6'h20 && card.req_wdata == 16'h0802)
            cleanup_reset_seen <= 1;
    end''')
    bench = bench.replace('rom[address[8:1]]', "(address < 32'h2000 ? rom[address[12:1]] : stack[address[15:1]])")
    bench = bench.replace('.mem_rdata(16\'b0)', '.mem_rdata(memory_response)')
    start = bench.index('                if (rw_n && address ==')
    end = bench.index('            if (ticks >', start)
    bench = bench[:start] + '''            end
            if (!as_n && !rw_n && address == 32'h8000) begin
                if (data_out != 0 || !release_read_seen || !release_seen || captures != 3 ||
                    !capture_valid || capture_status != 8'hE0 || capture_address != 16'hC07D)
                    $fatal(1, "original first handshake result mismatch result=%h", data_out);
                $display("PASS original Conf reset and first handshake on TG68K; CLR.B +19 read precedes release write");
                $finish;
            end
''' + bench[end:]
    if args.diagnostic:
        bench = bench.replace('!release_seen || captures != 3 ||\n'
                              "                    !capture_valid || capture_status != 8'hE0 || capture_address != 16'hC07D",
                              "!release_seen || !idle_read_seen || captures != 63 ||\n"
                              "                    !capture_valid || capture_status != 8'h28 || capture_address != 16'hC0E8")
        bench = bench.replace('original first handshake result mismatch result=%h',
                              'original diagnostic result mismatch result=%h')
        bench = bench.replace('result=%h", data_out);',
                              'result=%h pc=%h cpu=%h captures=%0d status=%h", data_out, instruction_address, card_cpu, captures, capture_status);')
        bench = bench.replace('$display("PASS original Conf reset and first handshake on TG68K; CLR.B +19 read precedes release write");',
                              '$display("PASS original Conf host checks return zero on TG68K; late C0E8 remains held, captures=%0d", captures);')
    if args.cleanup:
        bench = bench.replace("!release_seen || !idle_read_seen || captures != 63 ||\n"
                              "                    !capture_valid || capture_status != 8'h28 || capture_address != 16'hC0E8",
                              '!release_seen || !idle_read_seen || !late_capture_seen ||\n'
                              '                    !cleanup_reset_seen || capture_valid || captures != 63 ||\n'
                              '                    card.card.cpu_running || card.card.reset_pending ||\n'
                              '                    !card.card.drained || card.card.iwm_mode != 0')
        bench = bench.replace('$display("PASS original Conf host checks return zero on TG68K; late C0E8 remains held, captures=%0d", captures);',
                              '$display("PASS original Conf cleanup resets held C0E8, drains card work and returns zero via Pascal stack");')
        if args.cleanup_error:
            bench = bench.replace('if (data_out != 0 ||', "if (data_out != 16'h000D ||")
            bench = bench.replace('!idle_read_seen || !late_capture_seen ||',
                                  '!idle_read_seen || late_capture_seen ||')
            bench = bench.replace('capture_valid || captures != 63 ||',
                                  'capture_valid || captures != 44 ||')
            bench = bench.replace('PASS original Conf cleanup resets held C0E8, drains card work and returns zero via Pascal stack',
                                  'PASS original Conf auxiliary RAM failure returns error 13 via Pascal stack and resets card')
    bench = bench.replace('ticks > 20000', 'ticks > 200000')
    bench = bench.replace('transactions <= transactions + 1;', '''transactions <= transactions + 1;
                if (rw_n && card.req_offset == 6'h19) begin
                    if (!capture_valid || capture_status != 8'hE1 || release_seen)
                        $fatal(1, "release register read changed pending capture");
                    release_read_seen <= 1;
                end''')
    marker = '        repeat (10) @(negedge clk);'
    initial = ROOT / 'local/experiments/card-diagnostic-final/expected0.hex'
    payload = ROOT / 'local/experiments/firmware-memory/decoded/Conf_1001.payload.bin'
    card_image = bytearray.fromhex(initial.read_text())
    # Conf clears both RAM banks before uploading the diagnostic.
    card_image[:0x20000] = bytes(0x20000)
    uploaded = payload.read_bytes()
    card_image[0x2000:0x2000 + len(uploaded)] = uploaded
    # The candidate fetches auxiliary code while testing display banking.
    card_image[0x12000:0x12000 + len(uploaded)] = uploaded
    if args.cleanup_error:
        card_image[0x10000] = 0x80
    preload = WORK / 'handshake-card.hex'
    preload.write_text(''.join(f'{value:02x}\n' for value in card_image), encoding='ascii')
    bench = bench.replace(marker, '        $readmemh("' + linux(preload) + '''", initial_card);
        for (integer i = 0; i < 131072; i = i + 1)
            memory[i] = {initial_card[i * 2 + 1], initial_card[i * 2]};
''' + marker)
    if args.cleanup:
        bench = bench.replace(marker, '''        for (integer i = 0; i < 32768; i = i + 1) stack[i] = 0;
        stack[16'hFFE0 >> 1] = 0;
        stack[16'hFFE2 >> 1] = 16'h0200;
        stack[16'hFFE8 >> 1] = 16'hFFFF;
''' + marker)
    path = WORK / 'tb_handshake_bus.sv'
    path.write_text(bench, encoding='ascii')
    host = [MACLC / 'rtl/tg68k' / name for name in
            ('TG68K_Pack.sv', 'TG68K_ALU.v', 'TG68KdotC_Kernel.v', 'tg68k.v')]
    binary = WORK / 'handshake.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_launch_bus', '-o', linux(binary),
         linux(path), *map(linux, closure + host)])
    if args.control or args.idle_control:
        result = run_process(['vvp', linux(binary), '+program=' + linux(image)], timeout=30)
        print(result.stdout, end='')
        offset = '0c' if args.idle_control else '19'
        assert result.returncode and f'offset={offset}' in result.stdout and 'error=1' in result.stdout
        output = result.stdout
    else:
        output = run(['vvp', linux(binary), '+program=' + linux(image)])
    scope = ('Original Conf $046-$100 and diagnostic helpers' if args.diagnostic else
             'Original Conf $046-$080, $364 helper and WAIT')
    if args.cleanup:
        scope = 'Original Conf $046-$114, diagnostic helpers, cleanup and Pascal return; synthetic saved register/argument stack'
    record = {'control': args.control or args.idle_control or args.cleanup_error, 'result': output,
              'scope': scope + ' on actual TG68K; preloaded main/auxiliary diagnostic code and candidate firmware/vectors',
              'sha256': {str(p): sha(p) for p in [conf, initial, payload, preload, path, *closure, *host, Path(__file__)]}}
    result_name = ('cleanup-error' if args.cleanup_error else
                   'idle-control' if args.idle_control else 'control' if args.control else
                   'cleanup' if args.cleanup else 'diagnostic' if args.diagnostic else 'pass')
    (WORK / f'handshake-{result_name}.json').write_text(
        json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
