#!/usr/bin/env python3
"""Compose checked initializer snapshots with live service-4 rendering."""
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-service4-render'
PARENT = ROOT / 'fixtures/experiments/card-service4-cache'
spec = importlib.util.spec_from_file_location('cache_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def snapshot_inputs():
    inputs, snapshots = [], {}
    for task, names in [('card-display-init', ['world.bin', 'code-after.bin']),
                        ('card-display-switches', ['world.bin'])]:
        result_path = ROOT / f'fixtures/experiments/{task}/results.json'
        result = json.loads(result_path.read_text())
        for name, digest in result['inputs_sha256'].items():
            assert sha(Path(name)) == digest, 'changed snapshot source: ' + name
        inputs.append(result_path)
        for run in result['runs']:
            for name in names:
                path = Path(run['run_directory']) / name
                assert sha(path) == run['hashes'][name], 'changed snapshot: ' + str(path)
                snapshots[task, run['driver'], name] = path
                inputs.append(path)
    return snapshots, inputs


def prepare():
    pins_path = PARENT / 'results.json'
    assert sha(PARENT / 'prepare.py') == json.loads(pins_path.read_text())['inputs_sha256'][str(PARENT / 'prepare.py')]
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    _, snapshot_paths = snapshot_inputs()
    bench = sources[0]
    text = bench.read_text()
    text = once(text, '        wait(boundary);', "        wait(capture_valid && capture_address == 16'hC07D && capture_data == 4);")
    text = once(text, 'bridge_index <= 15;', 'bridge_index <= 16;')
    marker = "        if (card_cpu_address != 16'hC07D || opcodes != 2 || rtis != 1 ||"
    text = once(text, marker, """        wait(boundary);
        if (dut.platform.card.card.processor.cpu.reg_a != saved_a ||
            dut.platform.card.card.processor.cpu.reg_x != saved_x ||
            dut.platform.card.card.processor.cpu.reg_y != saved_y ||
            dut.platform.card.card.processor.cpu.reg_s != saved_s ||
            dut.platform.card.card.processor.cpu.reg_p != saved_p)
            $fatal(1, "service4 did not restore interrupted execution");
        if (card_cpu_address != 16'hFB65 || opcodes != 2 || rtis != 2 ||""")
    text = once(text, 'capture_count != switch_services + 3 || !capture_valid ||',
                'capture_count != switch_services + 3 || capture_valid ||')
    text = once(text, 'PASS service4 held fast=', 'PASS service4 rendered fast=')
    text = once(text, '$fatal(1, "monitor next service boundary mismatch");',
                '$fatal(1, "service4 boundary PC=%h opcode=%0d rti=%0d status=%h data=%h nmi=%0d service=%0d", card_cpu_address, opcodes, rtis, capture_status, capture_data, nmis, service_writes);')
    bench.write_text(text, encoding='ascii')
    candidate = WORK / 'card_irq_candidate.sv'
    card = once(candidate.read_text(),
        "assign boundary = capture_valid && capture_address == 16'hC07D && capture_data == 4;",
        "assign boundary = monitor_returns == 2 && cpu_valid && cpu_sync && cpu_address == 16'hFB65;")
    card = once(card, 'reg internal_rom, monitor_done;', 'reg internal_rom, monitor_done;\n    reg [1:0] monitor_returns;')
    assert card.count('monitor_done <= 0;') == 2
    card = re.sub(r'(?m)^( *)monitor_done <= 0;$',
                  r'\1monitor_done <= 0;\n\1monitor_returns <= 0;', card)
    card = once(card, 'if (rti_done && nmi_overlay) monitor_done <= 1;',
                'if (rti_done && nmi_overlay) begin\n                    monitor_done <= 1;\n                    monitor_returns <= monitor_returns + 1\'b1;\n                end')
    candidate.write_text(card, encoding='ascii')
    host_path = WORK / 'execute.lua'
    host = once(host_path.read_text(), "dofile('fixtures/experiments/card-service4-cache/bridge.lua')",
                "dofile('fixtures/experiments/card-service4-render/bridge.lua')")
    host = once(host, 'local taps = {}', 'local taps = {}\nlocal acks = 0\nlocal frame_size = tonumber(assert(os.getenv(\'IIE_FRAME_SIZE\')))')
    host = once(host, '        space:write_u32(world - 0x1236, card)', """        local function overlay(path, address)
            local file = assert(io.open(path, 'rb'))
            local contents = file:read('a')
            file:close()
            for i = 1, #contents do space:write_u8(address + i - 1, contents:byte(i)) end
        end
        overlay(assert(os.getenv('IIE_INIT_WORLD')), world - 0x5960)
        overlay(assert(os.getenv('IIE_INIT_CODE')), base)
        if os.getenv('IIE_WRONG_DESTINATION') == '1' then
            space:write_u32(world - 0x85e, space:read_u32(world - 0x85e) + 1)
        end
        local file = assert(io.open(assert(os.getenv('IIE_SWITCH_WORLD')), 'rb'))
        file:seek('set', 0x5960 - 0x972)
        local mode = file:read(2)
        file:close()
        assert(mode == string.char(0, 0), 'Expected completed reset-switch mode')
        space:write_u16(world - 0x972, 0)
        for i = 0x100000 - 64, 0x100000 + frame_size + 63 do space:write_u8(i, 0x5a) end
        space:write_u32(world - 0x1236, card)""")
    host = once(host, "            assert(not ack, 'Duplicate ACK')", """            acks = acks + 1
            assert(acks <= 2, 'Duplicate ACK')
            if acks == 2 then
                local function snapshot(name, address, size)
                    local file = assert(io.open(run .. '/' .. name, 'wb'))
                    file:write(space:read_range(address, address + size - 1, 8))
                    file:close()
                end
                snapshot('frame.bin', 0x100000 - 64, frame_size + 128)
                snapshot('preack-world.bin', world - 0x5960, 0x5c49)
                snapshot('code-after.bin', base, #bytes)
            end""")
    host = once(host, "cpu.debug:bpset(base + 0xa7e, '1',", "cpu.debug:bpset(base + 0x281c, 'temp0==1',")
    host = once(host, "        cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')", """        machine.debugger:command('temp0=0')
        cpu.debug:bpset(base + 0x1cae, 'b@(a5-88f)==4', 'temp0=1; g')
        cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')""")
    host = once(host, "'/trace.txt,:maincpu'", "'/trace.txt,:maincpu,noloop'")
    host = once(host, "        cpu.state['PC'].value = base + 0x2c4", """        space:write_u32(0x3efffc, base + 0x2c4)
        cpu.state['A7'].value = 0x3efffc
        cpu.state['PC'].value = base + 0x7ae""")
    host_path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py', HERE / 'bridge.lua', PARENT / 'prepare.py',
                                    pins_path, *snapshot_paths]
