#!/usr/bin/env python3
"""Check original D1 uploads on TG68K, then enter the original monitor."""
import argparse
import json
from pathlib import Path

from prepare_runtime import ROOT, MACLC, WORK, runtime_sources, sha
from check_runtime import linux, run, run_process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', action='store_true', help='Corrupt vector readback')
    parser.add_argument('--full-rom', action='store_true', help='Also upload the full monitor ROM; longer run')
    parser.add_argument('--driver', type=int, choices=(5, 6), help='Continue through original runtime service 1')
    parser.add_argument('--automatic', action='store_true', help='Use automatic reset mapping')
    parser.add_argument('--transition', action='store_true', help='Run Conf cleanup, upload and original runtime reset helpers together')
    parser.add_argument('--transition-prefix', action='store_true', help='Stop the transition at the first monitor display write')
    parser.add_argument('--transition-init', action='store_true', help='Run and check original display initialization before the transition prefix')
    parser.add_argument('--init-control', action='store_true', help='Inject a wrong initializer stride')
    parser.add_argument('--transition-render', action='store_true', help='Include automatic transition, initialization, lookup setup and first display handler; longer run')
    parser.add_argument('--render-setup-only', action='store_true', help='Stop after checking lookup tables and supplied glyphs')
    parser.add_argument('--lookup-control', action='store_true', help='Corrupt one CODE 1 lookup constant')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare and compile without running the simulation')
    parser.add_argument('--service-control', action='store_true', help='Return service 0 to the original driver')
    parser.add_argument('--display-store', action='store_true', help='Render and commit the first monitor display store')
    parser.add_argument('--display-control', action='store_true', help='Shift the display destination by one byte')
    parser.add_argument('--display-cells', type=int, default=1, help='Monitor clear cells to check, 1-960; full clear is a longer run')
    args = parser.parse_args()
    if args.transition_render:
        args.automatic = args.transition = args.transition_prefix = args.transition_init = True
        if args.init_control:
            parser.error('--transition-render excludes --init-control')
    if (args.render_setup_only or args.lookup_control) and not args.transition_render:
        parser.error('--render-setup-only and --lookup-control require --transition-render')
    if args.lookup_control and not args.render_setup_only:
        parser.error('--lookup-control requires --render-setup-only')
    if args.transition_init and not args.transition_prefix:
        parser.error('--transition-init requires --transition-prefix')
    if args.init_control and not args.transition_init:
        parser.error('--init-control requires --transition-init')
    if args.transition_prefix and not args.transition:
        parser.error('--transition-prefix requires --transition')
    if args.transition_prefix and args.full_rom:
        parser.error('--transition-prefix excludes --full-rom')
    if args.transition and (not args.automatic or not args.driver or args.control or
                           args.service_control or args.display_store):
        parser.error('--transition requires --automatic and --driver and excludes controls/display')
    if args.service_control and (not args.driver or args.control):
        parser.error('--service-control requires --driver and excludes --control')
    if args.display_store and (not args.driver or args.control or args.service_control):
        parser.error('--display-store requires --driver and excludes controls')
    if args.display_control and not args.display_store:
        parser.error('--display-control requires --display-store')
    if not 1 <= args.display_cells <= 960 or (args.display_cells != 1 and not args.display_store):
        parser.error('--display-cells requires --display-store and a count from 1 to 960')
    display_tag = 'display' if args.display_cells == 1 else f'display-{args.display_cells}'
    fixture = 'monitor-upload'
    if args.automatic:
        fixture += '-automatic'
    if args.transition:
        fixture += f'-transition-code{args.driver}'
    if args.transition_init:
        fixture += '-init' + ('-control' if args.init_control else '')
    if args.transition_render:
        fixture += '-render' + ('-setup' if args.render_setup_only else '') + ('-control' if args.lookup_control else '')
    if args.display_store:
        fixture += f'-code{args.driver}-{display_tag}-' + ('control' if args.display_control else 'pass')
    closure = runtime_sources()
    assets = ROOT / 'local/experiments/firmware-memory'
    code = assets / 'code/CODE_1.bin'
    monitor = assets / 'decoded/Monx_2606.payload.bin'
    resource_ids = (2606, 2607, 2611) if args.full_rom else (2607, 2611)
    resources = [assets / f'decoded/Monx_{n}.decoded.bin' for n in resource_ids]
    stream_bytes = sum(p.stat().st_size - 6 for p in resources)
    rom = bytearray(bytes.fromhex('4e71') * 32768)
    rom[:8] = bytes.fromhex('0000f00000000100')
    original = code.read_bytes()[0x4550:0x45bc]
    rom[0x1000:0x1000 + len(original)] = original
    rom[0x1000 + len(original):0x1002 + len(original)] = bytes.fromhex('4e75')
    program = bytearray.fromhex('227cfee00000')
    address = 0x4000
    for resource in resources:
        data = resource.read_bytes()
        assert len(data) == int.from_bytes(data[4:6], 'little') + 6
        rom[address:address + len(data)] = data
        program += bytes.fromhex('247c') + address.to_bytes(4, 'big')
        program += bytes.fromhex('207c') + (address + 6).to_bytes(4, 'big')
        program += bytes.fromhex('74004eb90000100033c200008000')
        address += (len(data) + 255) & ~255
    # Synthetic host reset/service caller; upload body above is unchanged.
    program += bytes.fromhex('137c0003000d337c08020020137c00200021137c00800020')
    program += bytes.fromhex('302900040c40fffc66f6137c008800204229000c')
    # ACK early captures, then hand the receiver to the selected host caller.
    if args.driver:
        # The driver must retain receiver register writes before service 1.
        program += bytes.fromhex('102900014a0067f8302900040240fff80c40c07867064229000c60e4')
    else:
        program += bytes.fromhex('102900014a0067f8302900040c40c07d67064229000c60e8')
    if args.driver:
        # Inject the same zero-volume A5 world used by the runtime bridge.
        rom[0x260] = 0
        program += bytes.fromhex('46fc27002a7c003000002b7cfee00000edca4ef90020281c')
    else:
        program += bytes.fromhex('1029000c13c00000800260fe')
    transition_inputs = []
    if args.transition:
        from startup_transition import prepare_host
        rom, transition_inputs = prepare_host(rom, program)
        if args.transition_init:
            from monitor_initializer import prepare_host as prepare_initializer_host
            rom = prepare_initializer_host(rom)
        if args.transition_render:
            from monitor_render import prepare_host as prepare_render_host
            rom = prepare_render_host(rom, args.driver)
    else:
        rom[0x100:0x100 + len(program)] = program
    image = WORK / f'{fixture}-host.hex'
    image.write_text(''.join(f'{int.from_bytes(rom[i:i+2], "big"):04x}\n'
                            for i in range(0, len(rom), 2)), encoding='ascii')
    card_image = bytearray(262144)
    payload = monitor.read_bytes()
    assert len(payload) == 16384
    if not args.full_rom:
        card_image[0x20000:0x24000] = payload
    card_image[0x2c300:0x2c400] = bytes.fromhex('00ea') * 128
    if args.transition:
        from startup_transition import prepare_card
        card_image, card_inputs = prepare_card(card_image)
        transition_inputs.extend(card_inputs)
    preload = WORK / f'{fixture}-card.hex'
    preload.write_text(''.join(f'{b:02x}\n' for b in card_image), encoding='ascii')
    bench = (ROOT / 'fixtures/experiments/maclc-iie-trial/tb_launch_bus.sv').read_text()
    bench = bench.replace('reg [1023:0] program_path;', 'reg [4095:0] program_path;')
    bench = bench.replace('.por_n(!reset),',
                          ".por_n(!reset), .runtime_mode(1'b0)," if args.automatic else
                          ".por_n(!reset), .runtime_mode(1'b1),")
    bench = bench.replace('reg [15:0] rom [0:255];', '''reg [15:0] rom [0:32767];
    reg [7:0] initial_card [0:262143];
    reg [15:0] memory [0:131071];
    reg [15:0] memory_response = 0;
    reg corrupt_seen = 0;
    integer uploads = 0, stream_reads = 0, stream_writes = 0;
    reg reset_entry_seen = 0;
    always @(posedge clk) begin
        if (!claim && !as_n && !rw_n && address[31:16] == 0) begin
            if (!uds_n) rom[address[15:1]][15:8] <= data_out[15:8];
            if (!lds_n) rom[address[15:1]][7:0] <= data_out[7:0];
        end
        if (mem_valid && !mem_rsp_valid) begin
            if (mem_write) memory[mem_addr] <= mem_data;
            memory_response <= memory[mem_addr];
        end
        if (card.req_valid && card.req_ready && !card.req_word && card.req_offset == 6'h10) begin
            if (card.req_write) stream_writes <= stream_writes + 1;
            else stream_reads <= stream_reads + 1;
        end
        if (card.card.cpu_ready && card.card.cpu_sync && !reset_entry_seen) begin
            if (card_cpu != 16'hFA62 || card.card.cpu_rdata != 8'hD8)
                $fatal(1, "wrong original monitor reset entry address=%h", card_cpu);
            reset_entry_seen <= 1;
        end
    end''')
    bench = bench.replace('rom[address[8:1]]', 'rom[address[15:1]]')
    bench = bench.replace(".mem_rdata(16'b0)", '.mem_rdata(memory_response)')
    start = bench.index('                if (rw_n && address ==')
    end = bench.index('            if (ticks >', start)
    bench = bench[:start] + '''            end
            if (!as_n && !rw_n && address == 32'h8000 && !active) begin
                active <= 1;
                uploads <= uploads + 1;
                if (data_out != 0) $fatal(1, "original upload readback failed result=%h", data_out);
            end
            if (!as_n && !rw_n && address == 32'h8002) begin
                if (uploads != 2 || data_out[15:8] != 1 || !capture_valid ||
                    capture_status != 8'hE0 || capture_address != 16'hC07D || captures != 26 ||
                    stream_reads != 108 || stream_writes != 108 || !reset_entry_seen)
                    $fatal(1, "uploaded monitor entry mismatch data=%h uploads=%0d captures=%0d", data_out, uploads, captures);
                $display("PASS original TG68K D1 receiver/vector upload and readback; original monitor reports service 1");
                $finish;
            end
''' + bench[end:]
    bench = bench.replace('ticks > 20000', 'ticks > 1000000')
    if args.full_rom:
        bench = bench.replace('ticks > 1000000', 'ticks > 10000000')
    bench = bench.replace('uploads != 2', f'uploads != {len(resources)}')
    bench = bench.replace('stream_reads != 108 || stream_writes != 108',
                          f'stream_reads != {stream_bytes} || stream_writes != {stream_bytes}')
    bench = bench.replace('        repeat (10) @(negedge clk);',
        '        $readmemh("' + linux(preload) + '''", initial_card);
        for (integer i = 0; i < 131072; i = i + 1)
            memory[i] = {initial_card[2*i+1], initial_card[2*i]};
        repeat (10) @(negedge clk);''')
    driver_inputs = []
    if args.driver:
        driver = assets / f'code/CODE_{args.driver}.bin'
        bench = bench.replace('ticks > 1000000)', 'ticks > 100000)')
        bench = bench.replace('"launch bus timeout address=%h claim=%0d dtack=%0d error=%0d", address, claim, dtack_n, error',
            '"driver timeout host=%h cpu=%h capture=%h status=%h ack=%b return=%b rti=%0d", '
            'address, card_cpu, capture_address, capture_status, service_ack, driver_return, rti_count')
        driver_image = WORK / (f'{fixture}-driver.hex' if args.display_store or args.transition_init else f'monitor-upload-code{args.driver}.hex')
        data = driver.read_bytes()
        assert len(data) <= 65536 and data[0x281c:0x281e] == bytes.fromhex('286d')
        data += bytes(65536 - len(data))
        driver_image.write_text(''.join(f'{int.from_bytes(data[i:i+2], "big"):04x}\n'
                                       for i in range(0, len(data), 2)), encoding='ascii')
        driver_inputs = [driver, driver_image]
        bench = bench.replace('    reg [15:0] rom [0:32767];', '''    reg [15:0] driver_code [0:32767];
    reg [15:0] world [0:32767];
    reg service_read = 0, service_ack = 0, driver_return = 0;
    reg [7:0] saved_a, saved_x, saved_y, saved_s, saved_p;
    integer rti_count = 0, service_reads = 0;
    reg [15:0] rom [0:32767];''')
        bench = bench.replace('assign data_in = claim ? card_data : rom[address[15:1]];', '''assign data_in = claim ? card_data : address[31:16] == 16'h0020 ?
        driver_code[address[15:1]] : address[31:16] == 16'h002F ?
        world[address[15:1]] : rom[address[15:1]];''')
        bench = bench.replace('        if (mem_valid && !mem_rsp_valid) begin', '''        if (!claim && !as_n && !rw_n && address[31:16] == 16'h002F) begin
            if (!uds_n) world[address[15:1]][15:8] <= data_out[15:8];
            if (!lds_n) world[address[15:1]][7:0] <= data_out[7:0];
        end
        if (card.card.opcode02_complete) begin
            if (card_cpu != 16'hFBDD) $fatal(1, "wrong monitor service opcode");
            saved_a <= card.card.processor.cpu.reg_a;
            saved_x <= card.card.processor.cpu.reg_x;
            saved_y <= card.card.processor.cpu.reg_y;
            saved_s <= card.card.processor.cpu.reg_s;
            saved_p <= card.card.processor.cpu.reg_p;
        end
        if (card.card.cpu_ready && card.card.rti_done) rti_count <= rti_count + 1;
        if (service_ack && !as_n && rw_n && address == 32'h0020281C)
            driver_return <= 1;
        if (mem_valid && !mem_rsp_valid) begin''')
        start = bench.index("            if (!as_n && !rw_n && address == 32'h8002)")
        end = bench.index('            if (ticks >', start)
        bench = bench[:start] + '''            if (claim && !dtack_n && !active && address == 32'hFEE0000C &&
                rw_n && service_reads == 2 && !service_ack) $fatal(1, "duplicate service read");
            if (claim && !dtack_n && !active && address == 32'hFEE0000C &&
                rw_n && capture_address == 16'hC07D && !service_ack) begin
                if (card_data[15:8] != 1 || capture_status != 8'hE0 || captures != 26)
                    $fatal(1, "wrong original service 1 capture");
                service_read <= 1;
                service_reads <= service_reads + 1;
            end
            if (claim && !dtack_n && !active && address == 32'hFEE0000C &&
                !rw_n && service_read && !service_ack) begin
                if (data_out[15:8] != 0 || uds_n || !lds_n)
                    $fatal(1, "wrong original driver ACK");
                service_ack <= 1;
            end
            if (service_ack && card.card.cpu_ready && card.card.cpu_sync && card_cpu == 16'hFBDF) begin
                if (card.card.processor.cpu.reg_a != saved_a ||
                    card.card.processor.cpu.reg_x != saved_x || card.card.processor.cpu.reg_y != saved_y ||
                    card.card.processor.cpu.reg_s != saved_s || card.card.processor.cpu.reg_p != saved_p)
                    $fatal(1, "original driver did not restore interrupted CPU registers");
                if (!driver_return || rti_count != 1 || service_reads != 2 || world[16'hF770 >> 1][7:0] != 1 ||
                    uploads != UPLOAD_COUNT || stream_reads != STREAM_BYTES ||
                    stream_writes != STREAM_BYTES || !reset_entry_seen)
                    $fatal(1, "original driver continuation mismatch latch=%h rti=%0d return=%b",
                        world[16'hF770 >> 1][7:0], rti_count, driver_return);
                $display("PASS original TG68K upload and driver service 1 ACK/return; card RTI to FBDF");
                $finish;
            end
''' + bench[end:]
        bench = bench.replace('UPLOAD_COUNT', str(len(resources))).replace('STREAM_BYTES', str(stream_bytes))
        bench = bench.replace('        repeat (10) @(negedge clk);',
            '        $readmemh("' + linux(driver_image) + '''", driver_code);
        for (integer i = 0; i < 32768; i = i + 1) world[i] = 0;
        repeat (10) @(negedge clk);''')
        if args.service_control:
            bench = bench.replace('claim ? card_data :',
                "claim ? ((address == 32'hFEE0000C && capture_address == 16'hC07D && !service_ack) ? 16'h00FF : card_data) :")
            bench = bench.replace('''                if (!driver_return || rti_count''', '''                if (driver_return && world[16'hF770 >> 1][7:0] == 0 && rti_count == 1) begin
                    $display("PASS wrong service selects original ID0 path; service 1 latch check rejects continuation");
                    $finish;
                end
                $fatal(1, "service control did not select ID0");
                if (!driver_return || rti_count''')
    if args.display_store:
        from monitor_display import prepare_display
        bench, display_inputs = prepare_display(bench, args.driver, driver_image, args.display_control, args.display_cells)
        driver_inputs.extend(display_inputs)
    if args.control:
        bench = bench.replace('memory_response <= memory[mem_addr];', '''memory_response <= memory[mem_addr];
            if (!mem_write && mem_addr == 17'h13FFD && stream_writes == STREAM_BYTES && !corrupt_seen) begin
                memory_response <= memory[mem_addr] ^ 16'h0001;
                corrupt_seen <= 1;
            end''')
        bench = bench.replace('if (data_out != 0) $fatal(1, "original upload readback failed result=%h", data_out);', '''if (uploads < LAST_UPLOAD && data_out != 0) $fatal(1, "earlier upload failed");
                if (uploads == LAST_UPLOAD) begin
                    if (data_out != 16'h0A2E || !corrupt_seen || card.card.cpu_running)
                        $fatal(1, "corrupt readback was not rejected result=%h", data_out);
                    $display("PASS corrupted vector readback returns original error 0A2E before monitor launch");
                    $finish;
                end''')
        bench = bench.replace('STREAM_BYTES', str(stream_bytes)).replace('LAST_UPLOAD', str(len(resources) - 1))
    if args.transition:
        from startup_transition import prepare_bench
        bench = prepare_bench(bench, args.transition_prefix)
        if args.transition_init:
            from monitor_initializer import prepare_bench as prepare_initializer_bench
            bench, init_inputs = prepare_initializer_bench(bench, args.driver, args.init_control)
            transition_inputs.extend(init_inputs)
        if args.transition_render:
            from monitor_render import prepare_bench as prepare_render_bench
            bench, render_inputs = prepare_render_bench(bench, args.driver, args.render_setup_only, args.lookup_control)
            transition_inputs.extend(render_inputs)
    path = WORK / (f'tb_{fixture}.sv' if args.display_store or args.automatic else 'tb_monitor_upload.sv')
    path.write_text(bench, encoding='ascii')
    host = [MACLC / 'rtl/tg68k' / n for n in
            ('TG68K_Pack.sv', 'TG68K_ALU.v', 'TG68KdotC_Kernel.v', 'tg68k.v')]
    binary = WORK / f'{fixture}.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_launch_bus', '-o', linux(binary),
         linux(path), *map(linux, closure + host)])
    command = ['vvp', linux(binary), '+program=' + linux(image)]
    if args.prepare_only:
        print('Prepared and compiled: ' + str(binary))
        return
    if args.full_rom or args.display_cells > 42 or (args.transition_render and not args.render_setup_only):
        result = run_process(command, timeout=900 if args.display_cells > 42 or args.transition_render else 300)
        print(result.stdout, end='')
        if result.returncode:
            raise RuntimeError(result.stderr + '\nMonitor upload/display simulation failed')
        output = result.stdout
    else:
        output = run(command)
    if args.transition_render and not args.render_setup_only:
        from monitor_render import check_pixels
        transition_inputs.extend(check_pixels(args.driver))
        output += 'PASS first transition display framebuffer and guards match independent text oracle\n'
    inputs = [code, monitor, *resources, *driver_inputs, *transition_inputs, image, preload, path, *closure, *host, Path(__file__)]
    preload_scope = 'external slot 3' if args.full_rom else 'monitor ROM and external slot 3'
    record = {'control': args.control, 'full_rom_upload': args.full_rom, 'result': output,
              'automatic': args.automatic,
              'transition': args.transition,
              'transition_prefix': args.transition_prefix,
              'transition_init': args.transition_init, 'init_control': args.init_control,
              'transition_render': args.transition_render, 'render_setup_only': args.render_setup_only,
              'lookup_control': args.lookup_control,
              'driver': args.driver, 'service_control': args.service_control,
              'display_store': args.display_store, 'display_control': args.display_control,
              'display_cells': args.display_cells if args.display_store else 0,
              'uploaded_resource_ids': resource_ids, 'stream_bytes_per_direction': stream_bytes,
              'scope': 'Original CODE 1 $4550-$45BC upload/readback, decoded D1 resources; '
                       f'synthetic reset/ACK caller, preloaded {preload_scope}; candidate runtime mapping',
              'sha256': {str(p): sha(p) for p in inputs}}
    name = 'control' if args.control else 'pass'
    if args.automatic:
        name = 'automatic-' + name
    if args.full_rom:
        name = 'full-' + name
    if args.driver:
        if args.service_control:
            name = name.replace('pass', 'service-control')
        name = f'code{args.driver}-' + name
        record['scope'] += '; original TG68K receiver register save/restore and service 1 dispatch; '
        record['scope'] += 'injected zero-volume A5 world'
        if not args.display_store:
            record['scope'] += ', stop after RTI to $FBDF'
    if args.display_store:
        name = name.replace('pass', display_tag + ('-control' if args.display_control else '-pass'))
        record['scope'] += '; initializer snapshots and injected mode-zero dispatch from original table; '
        record['scope'] += f'stop after {args.display_cells} display store ACKs, memory commits and rendered cells'
    if args.transition:
        name = 'transition-' + name
        if args.transition_prefix:
            name = 'prefix-' + name
        if args.transition_init:
            name = 'init-' + name
            if args.init_control:
                name = name.replace('pass', 'stride-control')
        record['scope'] = ('Original Conf $046-$114 cleanup, CODE 1 upload/readback, driver $2A2 '
                           'mask setup, $4CA reset handshake and runtime dispatch on TG68K; '
                           'automatic mapping, no synthetic capture ACKs; diagnostic firmware/code '
                           'preload, supplied A5 buffers and slot 3; full $450 reset/OS setup excluded; '
                           f'monitor ROM {"uploaded" if args.full_rom else "preloaded"}')
        if args.transition_prefix and not args.init_control:
            record['scope'] += '; stop with first $05FB display write held, before renderer/service 1'
        if args.transition_init:
            record['scope'] += '; original driver initializer in the same TG68K session, independent full-world/code oracle; supplied stride/geometry and modeled A81F NIL response; no initializer snapshots'
        if args.init_control:
            record['scope'] += '; wrong-stride control stops at the rejected second row offset, before runtime reset'
        if args.transition_render:
            name = 'render-' + name
            if args.render_setup_only:
                name = 'setup-' + name
            if args.lookup_control:
                name = name.replace('pass', 'lookup-control')
            record['scope'] = ('Consecutive Conf cleanup, upload, original driver initialization and CODE 1 lookup generation on TG68K; '
                               'supplied captured QuickDraw glyph image, stride/geometry and modeled A81F NIL; '
                               'diagnostic firmware/code, monitor ROM and slot-3 preloads; full original caller/OS setup excluded; ')
            record['scope'] += ('stop before runtime reset' if args.render_setup_only else
                               'original $047E upload-context clear, first 05FB store ACK/commit, cache data and framebuffer after host returns to polling; no service 1 qualification')
            if args.lookup_control:
                record['scope'] += '; changed disposable CODE 1 constant rejected at wide entry 1'
    (WORK / f'monitor-upload-{name}.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
