#!/usr/bin/env python3
"""Compose original prompt input with live keyboard arrival and service 6."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-monitor-key-input'
PROMPT = HERE.parent / 'card-monitor-prompt'
POST = HERE.parent / 'card-monitor-post-match'
BASE = HERE.parent / 'card-boot-service3'
MATCH = HERE.parent / 'card-boot-service3-live-match'
PARENT = HERE.parent / 'card-boot-service2'
spec = importlib.util.spec_from_file_location('key_prompt_prepare', PROMPT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    pins_path = HERE.parent / 'card-keyboard-monitor/results-5-48.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    pinned = next(Path(name) for name in pins if 'inputs' in Path(name).parts and name.endswith('card_irq_candidate.sv'))
    assert sha(pinned) == pins[str(pinned)]
    for fragment in ("if (cpu_address == 16'hC010 && !test_ignore_key_clear) keyboard[7] <= 0;",
                     "if (keyboard_write) keyboard <= {1'b1, sidefx_wdata[6:0]};",
                     "wire allowed_io = cpu_address == 16'hC010 || service_register ||"):
        assert fragment in pinned.read_text(), fragment
    card = WORK / 'card_irq_candidate.sv'
    text = card.read_text()
    text = once(text, '    reg input_started;', '    reg test_release_idle = 0;\n    reg input_started;')
    text = once(text, "cpu_address == 16'hC27D && idle_reads == 260;", """((cpu_address == 16'hC27D && idle_reads == 260 && !test_release_idle) ||
         (service_returns == 6 && cpu_address == 16'hFD7A));""")
    text = once(text, "service_returns == 5 && cpu_valid && cpu_sync &&", "cpu_valid && cpu_sync &&")
    text = once(text, "if (!cpu_write && cpu_address == 16'hC010) keyboard[7] <= 0;",
                "if (cpu_address == 16'hC010 && !$test$plusargs(\"missing_clear\")) keyboard[7] <= 0;")
    text = once(text, 'wire allowed_io = service_register ||',
                "wire allowed_io = cpu_address == 16'hC010 || service_register ||")
    text = once(text, 'if (keyboard_write) keyboard <= sidefx_wdata[7:0];',
                "if (keyboard_write) keyboard <= {$test$plusargs(\"missing_strobe\") ? 1'b0 : 1'b1, sidefx_wdata[6:0]};")
    card.write_text(text, encoding='ascii')
    bench = sources[0]
    text = bench.read_text()
    text = once(text, '    reg input_seen = 0;', (HERE / 'key.sv').read_text() + '\n    reg input_seen = 0;')
    text = once(text, 'dut.platform.card.card.input_started && cpu_ready && !dut.platform.card.card.cpu_write &&',
                'dut.platform.card.card.input_started && !key_injected && cpu_ready && !dut.platform.card.card.cpu_write &&')
    text = once(text, '        $readmemh(image_path, expected);', '''        if (!$value$plusargs("key=%d", raw_key) ||
            !$value$plusargs("key_instructions=%s", key_instruction_path)) $fatal(1, "missing key inputs");
        $readmemh(image_path, expected);''')
    text = once(text, '                if (bridge_write == 0 && bridge_width == 8 && bridge_offset == 1)', '''                if (bridge_index == 265) begin
                    wait(boundary);
                    @(negedge clk_sys);
                    check_idle();
                    $fclose(instructions);
                    instructions = $fopen(key_instruction_path, "w");
                    if (instructions == 0) $fatal(1, "key trace open failed");
                    transact(1, 0, 24, raw_key, 0);
                    $display("KEY_DELIVERY raw=%h offset=18 width=8 pulses=%0d total_pds=%0d", 8'(raw_key), keyboard_pulses, transaction_count);
                    if (keyboard_pulses != 1 || dut.platform.card.card.keyboard !== (8'(raw_key) | 8'h80))
                        $fatal(1, "key strobe creation missing keyboard=%h", dut.platform.card.card.keyboard);
                    key_injected = 1;
                    $display("KEY arrival raw=%h latch=%h pulses=%0d", 8'(raw_key), dut.platform.card.card.keyboard, keyboard_pulses);
                    dut.platform.card.card.test_release_idle = 1;
                    #1;
                end
                if (bridge_write == 0 && bridge_width == 8 && bridge_offset == 1)''')
    for counter in ('host_returns', 'register_reads'):
        text = once(text, f'if ({counter} >= 20 && register_index == 3)',
                    f'if ({counter} >= 20 && {counter} < 25 && register_index == 3)')
        marker = f'if ({counter} >= 20 && {counter} < 25 && register_index == 3) return_value = return_value | 8\'h02;'
        text = once(text, marker, marker + f'''
                if ({counter} >= 25 && register_index == 0 && (8'(raw_key) | 8'h80) == 8'hFF) return_value = 8'h88;
                if ({counter} >= 25 && register_index == 3)
                    return_value = (8'(raw_key) | 8'h80) == 8'h95 ? return_value | 8'h02 : return_value & 8'hFD;''')
    text = once(text, "(card_cpu_address == 16'hFAC2 && register_reads == 25 && rti_contexts == 4)",
                "(card_cpu_address == 16'hFAC2 && register_reads == 25 && rti_contexts == 4) ||\n"
                "             (card_cpu_address == 16'hFD7A && register_reads == 30 && rti_contexts == 5)")
    text = once(text, "(rti_contexts == 2 ? 8'(boot_a) : saved_a)",
                "(rti_contexts == 2 ? 8'(boot_a) : rti_contexts == 5 && saved_a == 8'hFF ? 8'h88 : saved_a)")
    text = once(text, "rti_contexts == 4 ? saved_p | 8'h02 : saved_p)",
                "rti_contexts == 4 ? saved_p | 8'h02 : rti_contexts == 5 ? (saved_a == 8'h95 ? saved_p | 8'h02 : saved_p & 8'hFD) : saved_p)")
    text = once(text, "card_cpu_address !== 16'hC27D || opcodes != 5 || rtis != 5 || nmis != 5",
                "card_cpu_address !== 16'hFD7A || opcodes != 6 || rtis != 6 || nmis != 6")
    text = once(text, 'register_writes != 25 || register_reads != 25 || service_writes != 25',
                'register_writes != 30 || register_reads != 30 || service_writes != 30')
    text = once(text, 'host_returns != 25 || switch_services != 5 || rti_contexts != 5',
                'host_returns != 30 || switch_services != 5 || rti_contexts != 6')
    text = once(text, '        check_idle();\n        $display("EXCHANGE', '        check_key();\n        $display("EXCHANGE')
    text = once(text, 'capture_count != switch_services + 57', 'capture_count != switch_services + 68')
    text = once(text, 'PASS prompt fast=', 'PASS key-input fast=')
    bench.write_text(text, encoding='ascii')
    host = WORK / 'host.lua'
    text = host.read_text()
    text = once(text, 'if return_writes == 25 and cold_acks == 1 then', 'if return_writes == 30 then')
    text = once(text, "if return_writes == 25 and cpu.state['PC'].value ~= base + 0x1cb2 then",
                "if return_writes == 25 and cold_acks == 0 and cpu.state['PC'].value ~= base + 0x1cb2 then")
    text = once(text, 'service_acks <= 5', 'service_acks <= 6')
    text = once(text, 'return_writes <= 25', 'return_writes <= 30')
    text = once(text, "                    elseif service_acks == 5 then", """                    elseif service_acks == 6 then
                        assert(space:read_u8(world - 0x88f) == 6, 'Expected keyboard service 6')
                        snapshot('key-preack-world.bin', world - 0x5960, 0x5c49)
                        snapshot('key-preack-code.bin', base, #bytes)
                        snapshot('key-preack-frame.bin', 0x100000 - 64, frame_size + 128)
                    elseif service_acks == 5 then""")
    text = once(text, "'temp0=0; temp1=0; temp2=0; temp3=0; temp4=0'", "'temp0=0; temp1=0; temp2=0; temp3=0; temp4=0; temp5=0'")
    text = once(text, "        cpu.debug:bpset(base + 0x281c, 'temp0==3 && temp4==1',", """        cpu.debug:bpset(base + 0x281c, 'temp4==1 && temp5==0',
            'save "' .. run .. '/prekey-world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/prekey-code.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'd@310000=pc; d@310004=a7; save "' .. run .. '/prekey-state.bin",310000,8; temp4=2; g')
        cpu.debug:bpset(base + 0x1f38, '1', 'temp5=1; g')
        cpu.debug:bpset(base + 0x1c2e, 'temp5==1', 'temp5=2; g')
        cpu.debug:bpset(base + 0x281c, 'temp5==2',""")
    text = once(text, '.. \'printf "BS3_BOUNDARY pc=%08X sp=%08X",pc,a7; trace off,:maincpu; quit\'',
                '.. \'save "\' .. run .. \'/key-final-frame.bin",fffc0,\' .. string.format(\'%x\', frame_size + 128) .. \'; \'\n'
                '            .. \'printf "KEY_BOUNDARY pc=%08X sp=%08X",pc,a7; trace off,:maincpu; quit\'')
    host.write_text(text, encoding='ascii')
    return sources, image, inputs + [pins_path, pinned, HERE / 'prepare.py', HERE / 'key.sv',
                                    HERE / 'checks.py', HERE / 'verify.py', PROMPT / 'run.py']
