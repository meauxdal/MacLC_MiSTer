#!/usr/bin/env python3
"""Map the original monitor and normal NMI receiver in a bounded candidate."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = ROOT / 'fixtures/experiments/card-reset-system'
spec = importlib.util.spec_from_file_location('reset_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
BASE_WORK = parent.WORK
WORK = ROOT / 'local/experiments/card-monitor-entry'
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    closure, _, inputs = parent.prepare()
    pins_path = PARENT / 'results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for path in closure:
        original = BASE_WORK / path.name if path.parent == WORK else path
        assert sha(path) == pins[str(original)], 'changed reset source: ' + str(original)
    card = WORK / 'card_irq_candidate.sv'
    text = once(card.read_text(), '#(parameter PACE_FAST = 0,',
                "#(parameter [2:0] GAME_INPUTS = 3'b000, parameter [7:0] FLOATING_DATA = 8'h00,\n"
                '                            parameter PACE_FAST = 0,')
    text = once(text, '    wire cpu_ready, pace_due;', '''    reg internal_rom, monitor_done;
    reg slot3_rom;
    reg [7:0] card_mode;
    reg [7:0] service_regs [0:4];
    wire mode_store80, mode_page2, mode_text, mode_mixed, mode_hires, mode_altchar, mode_col80;
    card_display_state display_state (
        .clk(clk), .reset(!por_n || !cpu_running), .valid(cpu_valid), .complete(cpu_ready),
        .address(cpu_address), .write(cpu_write), .aux(ram_address[16]), .double_hires(1'b0), .motor(1'b0),
        .altchar(mode_altchar), .text_mode(mode_text), .hires(mode_hires), .annunciator3(),
        .col80(mode_col80), .mixed(mode_mixed),
        .page2(mode_page2), .store80(mode_store80), .active_page2(),
        .text_page_active(), .hires_page_active(), .display_trap(), .io_trap()
    );
    wire receiver_read = nmi_overlay && !cpu_write &&
                         cpu_address >= 16'hD000 && cpu_address < 16'hD066;
    wire monitor_read = !cpu_write && cpu_address >= 16'hC100 && !high_read;
    wire service_register = cpu_address >= 16'hC078 && cpu_address <= 16'hC07C;
    wire cpu_ready, pace_due;''')
    text = once(text, "wire io_space = cpu_address >= 16'hC000 && cpu_address < 16'hD000;",
                "wire io_space = cpu_address >= 16'hC000 && cpu_address < 16'hC100;")
    text = once(text, 'wire allowed_io = io_trap ||', '''wire allowed_io = service_register ||
                      cpu_address == 16'hC015 || cpu_address == 16'hC018 || cpu_address == 16'hC02B ||
                      (cpu_address >= 16'hC01A && cpu_address <= 16'hC01F) ||
                      cpu_address == 16'hC007 || cpu_address == 16'hC006 ||
                      cpu_address == 16'hC00A || cpu_address == 16'hC00B || cpu_address == 16'hC017 ||
                      (cpu_address >= 16'hC061 && cpu_address <= 16'hC063) ||
                      (cpu_address >= 16'hC050 && cpu_address <= 16'hC05F) || io_trap ||''')
    text = once(text, 'wire [17:0] physical = firmware_test ?', '''wire [17:0] physical = receiver_read ? 18'h25000 + {2'b0, cpu_address} - 18'h0D000 :
        monitor_read && cpu_address >= 16'hFFFA ? 18'h27FFA + {2'b0, cpu_address} - 18'h0FFFA :
        monitor_read ? 18'h20000 + {2'b0, cpu_address} - 18'h0C000 : firmware_test ?''')
    text = once(text, '!io_space && !firmware_read && !firmware_test &&',
                '!io_space && !monitor_read && !receiver_read && !firmware_read && !firmware_test &&')
    text = once(text, "assign boundary = cpu_valid && cpu_sync && cpu_address == 16'h2043;",
                'assign boundary = monitor_done && cpu_valid && cpu_sync;')
    text = once(text, "            16'hC019: cpu_rdata = {control[6], 7'b0};", '''            16'hC019: cpu_rdata = {control[6], 7'b0};
            16'hC015: cpu_rdata = {internal_rom, 7'b0};
            16'hC017: cpu_rdata = {slot3_rom, 7'b0};
            16'hC018: cpu_rdata = {mode_store80, 7'b0};
            16'hC01A: cpu_rdata = {mode_text, 7'b0};
            16'hC01B: cpu_rdata = {mode_mixed, 7'b0};
            16'hC01C: cpu_rdata = {mode_page2, 7'b0};
            16'hC01D: cpu_rdata = {mode_hires, 7'b0};
            16'hC01E: cpu_rdata = {mode_altchar, 7'b0};
            16'hC01F: cpu_rdata = {mode_col80, 7'b0};
            16'hC02B: cpu_rdata = card_mode;
            16'hC061: cpu_rdata = {GAME_INPUTS[0], 7'b0};
            16'hC062: cpu_rdata = {GAME_INPUTS[1], 7'b0};
            16'hC063: cpu_rdata = {GAME_INPUTS[2], 7'b0};
            16'hC078, 16'hC079, 16'hC07A, 16'hC07B, 16'hC07C:
                cpu_rdata = service_regs[cpu_address[2:0]];
            16'hC050, 16'hC051, 16'hC052, 16'hC053,
            16'hC054, 16'hC055, 16'hC056, 16'hC057,
            16'hC058, 16'hC059, 16'hC05A, 16'hC05B,
            16'hC05C, 16'hC05D, 16'hC05E, 16'hC05F: cpu_rdata = FLOATING_DATA;''')
    text = once(text, '            reset_restart <= 0;', '''            reset_restart <= 0;
            internal_rom <= 0;
            card_mode <= 0;
            slot3_rom <= 0;
            monitor_done <= 0;
            service_regs[0] <= 0;
            service_regs[1] <= 0;
            service_regs[2] <= 0;
            service_regs[3] <= 0;
            service_regs[4] <= 0;''')
    text = once(text, '                reset_pending <= 0;', '''                reset_pending <= 0;
                internal_rom <= 0;
                card_mode <= 0;
                slot3_rom <= 0;
                monitor_done <= 0;
                service_regs[0] <= 0;
                service_regs[1] <= 0;
                service_regs[2] <= 0;
                service_regs[3] <= 0;
                service_regs[4] <= 0;''')
    text = once(text, '                cpu_completed <= cpu_completed + 1;', '''                cpu_completed <= cpu_completed + 1;
                if (cpu_write && cpu_address == 16'hC007) internal_rom <= 1;
                if (cpu_write && cpu_address == 16'hC006) internal_rom <= 0;
                if (cpu_write && cpu_address == 16'hC00A) slot3_rom <= 0;
                if (cpu_write && cpu_address == 16'hC00B) slot3_rom <= 1;
                if (cpu_write && cpu_address == 16'hC02B) card_mode <= cpu_wdata;
                if (cpu_write && service_register) service_regs[cpu_address[2:0]] <= cpu_wdata;
                if (rti_done && nmi_overlay) monitor_done <= 1;''')
    card.write_text(text, encoding='ascii')
    display_pins = ROOT / 'fixtures/experiments/card-display-state/results.json'
    display_hashes = json.loads(display_pins.read_text())['inputs_sha256']
    for name in ('fixtures/experiments/card-display-state/card_display_state.sv',
                 'fixtures/experiments/card-video/card_trap_decode.sv'):
        path = ROOT / name
        assert sha(path) == display_hashes[name], 'changed display component: ' + name
        closure.append(path)
    return closure, inputs + [Path(__file__), PARENT / 'prepare.py', pins_path, display_pins]


if __name__ == '__main__':
    prepare()
