#!/usr/bin/env python3
"""Run the original driver initializer before the transition reset helpers."""
import importlib.util

from prepare_runtime import ROOT, WORK
from check_runtime import linux


def prepare_host(rom):
    # Model _Get1Resource through the CPU's A-line exception and original return.
    rom[0x28:0x2c] = (0x700).to_bytes(4, 'big')
    rom[0x700:0x70a] = bytes.fromhex('2f7c0000072000024e73')
    stub = bytes.fromhex('42af00065c8f4ef9002000d2')
    rom[0x720:0x720 + len(stub)] = stub
    rom[0xa5a:0xa5c] = bytes.fromhex('5678')
    call = bytes.fromhex('4eb90020000833fc000100008006')
    start = rom.index(bytes.fromhex('4eb9002002a2'), 0x300, 0x1000)
    end = start + 18
    tail = bytes(rom[start:end])
    rom[start:start + len(call) + len(tail)] = call + tail
    return rom


def prepare_bench(bench, driver, control=False):
    oracle = ROOT / 'fixtures/experiments/card-display-init/run.py'
    spec = importlib.util.spec_from_file_location('initializer_oracle', oracle)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = bytearray(0x102e9)
    expected[0xa6a0:0x102e9] = module.expected(driver)
    # This fixture supplies stride directly rather than a Macintosh PixMap.
    expected[0xedf8:0xedfc] = bytes(4)
    expected[0xedca:0xedce] = bytes.fromhex('fee00000')
    for offset, value in ((0xedd6, 0x2f8000), (0xedda, 0x2f4000), (0xedde, 0x2f0000)):
        expected[offset:offset + 4] = value.to_bytes(4, 'big')
    world_image = WORK / f'transition-init-code{driver}-expected.hex'
    world_image.write_text(''.join(f'{int.from_bytes(expected[i:i+2].ljust(2, bytes(1)), "big"):04x}\n'
                                  for i in range(0, len(expected), 2)), encoding='ascii')
    original = (ROOT / f'local/experiments/firmware-memory/code/CODE_{driver}.bin').read_bytes()
    code = bytearray(original)
    start = 0x669c if driver == 5 else 0x5378
    code[start:start + 4096] = module.table(driver)
    code += bytes(65536 - len(code))
    code_image = WORK / f'transition-init-code{driver}-code-expected.hex'
    code_image.write_text(''.join(f'{int.from_bytes(code[i:i+2], "big"):04x}\n'
                                 for i in range(0, len(code), 2)), encoding='ascii')
    bench = bench.replace('reg [15:0] world [0:32767];', '''reg [15:0] world [0:65535];
    reg [15:0] init_world_expected [0:33140];
    reg [15:0] init_code_expected [0:32767];
    reg initializer_done = 0, resource_seen = 0, resource_active = 0;
    integer init_index;
    integer resource_calls = 0;
    reg [15:0] exception_sp = 16'hFFFF;''')
    bench = bench.replace("address[31:16] == 16'h002F", "(address[31:16] == 16'h002F || address[31:16] == 16'h0030)")
    bench = bench.replace('world[address[15:1]]', "world[(address - 32'h002F0000) >> 1]")
    marker = '        if (mem_valid && !mem_rsp_valid) begin'
    assert marker in bench
    bench = bench.replace(marker, '''        if (!claim && !as_n && !rw_n && address[31:16] == 16'h0020) begin
            if (!uds_n) driver_code[address[15:1]][15:8] <= data_out[15:8];
            if (!lds_n) driver_code[address[15:1]][7:0] <= data_out[7:0];
        end
        if (!as_n && rw_n && address == 32'h002000D0 && !resource_seen) begin
            resource_seen <= 1;
        end
        if (as_n) resource_active <= 0;
        if (resource_seen && !initializer_done && !as_n && !rw_n &&
            address[31:16] == 0 && address[15:0] < exception_sp)
            exception_sp <= address[15:0];
        if (!as_n && rw_n && address == 32'h700 && !resource_active) begin
            resource_active <= 1;
            resource_calls <= resource_calls + 1;
            if (rom[(exception_sp + 2) >> 1] != 16'h0020 ||
                rom[(exception_sp + 4) >> 1] != 16'h00D0 ||
                rom[(exception_sp + 8) >> 1] != 16'h0A2E ||
                rom[(exception_sp + 10) >> 1] != 16'h4544 ||
                rom[(exception_sp + 12) >> 1] != 16'h4546 ||
                rom[16'h0A5A >> 1] != 16'h1234)
                $fatal(1, "initializer resource exception/arguments mismatch sp=%h", exception_sp);
        end
        if (!as_n && !rw_n && address == 32'h8006 && !initializer_done) begin
            if (!conf_done || uploads != 2 || stream_reads != 108 || stream_writes != 108 ||
                data_out != 1 || resource_calls != 1 || rom[16'h0A5A >> 1] != 16'h5678 ||
                card.card.cpu_running || card.card.reset_pending || !card.card.drained || capture_valid)
                $fatal(1, "initializer return/resource state mismatch");
            for (init_index = 16'hA6A0 >> 1; init_index < 33140; init_index = init_index + 1)
                if (world[init_index] !== init_world_expected[init_index]) begin
                    INIT_WORLD_MISMATCH
                end
            if (world[33140][15:8] !== init_world_expected[33140][15:8])
                $fatal(1, "initializer last world byte mismatch");
            for (init_index = 0; init_index < 32768; init_index = init_index + 1)
                if (driver_code[init_index] !== init_code_expected[init_index])
                    $fatal(1, "initializer code/table mismatch word=%0d", init_index);
            INIT_WORLD_MATCH
            initializer_done <= 1;
            $display("PHASE original driver initializer world and complete driver/table match independent oracle");
        end
''' + marker, 1)
    bench = bench.replace('if (!runtime_seen || !reset_entry_seen ||',
                          'if (!initializer_done || !runtime_seen || !reset_entry_seen ||')
    bench = bench.replace('for (integer i = 0; i < 32768; i = i + 1) world[i] = 0;',
                          'for (integer i = 0; i < 65536; i = i + 1) world[i] = 0;')
    marker = '        repeat (10) @(negedge clk);'
    setup = '''        {world[16'hF7A6 >> 1], world[16'hF7A8 >> 1]} = 32'h00200004;
        {world[16'hEF6C >> 1], world[16'hEF6E >> 1]} = 32'h00100000;
        world[16'hEF6A >> 1] = 640;
        world[16'hEF5A >> 1] = 480;
        world[16'hEF5E >> 1] = DEPTH;
        world[16'hEDFC >> 1] = 16'h1234;
        world[16'hF778 >> 1] = STRIDE;
        {world[16'hF740 >> 1], world[16'hF742 >> 1]} = 32'hDEADBEEF;
        $readmemh("WORLD_EXPECTED", init_world_expected);
        $readmemh("CODE_EXPECTED", init_code_expected);
'''
    setup = setup.replace('DEPTH', str(4 if driver == 5 else 1)).replace('STRIDE', str((320 if driver == 5 else 80) + int(control)))
    setup = setup.replace('WORLD_EXPECTED', linux(world_image)).replace('CODE_EXPECTED', linux(code_image))
    bench = bench.replace(marker, setup + marker)
    mismatch = '$fatal(1, "initializer world mismatch word=%0d actual=%h expected=%h", init_index, world[init_index], init_world_expected[init_index]);'
    match = ''
    if control:
        stride = 320 if driver == 5 else 80
        mismatch = f'''if (init_index != (16'hEFA4 >> 1) ||
                        world[init_index] != {(stride + 1) * 16} || init_world_expected[init_index] != {stride * 16})
                        $fatal(1, "initializer control failed outside row-stride boundary word=%0d", init_index);
                    $display("PASS wrong initializer stride rejected by independent world oracle at second row offset"); $finish;'''
        match = '$fatal(1, "wrong initializer stride escaped world oracle");'
    bench = bench.replace('INIT_WORLD_MISMATCH', mismatch).replace('INIT_WORLD_MATCH', match)
    bench = bench.replace('PASS consecutive Conf cleanup, upload and original reset helpers;',
                          'PASS consecutive Conf cleanup, upload, original driver initialization and reset helpers;')
    return bench, [oracle, world_image, code_image, ROOT / 'tools/monitor_initializer.py']
