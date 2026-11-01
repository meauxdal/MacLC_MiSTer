#!/usr/bin/env python3
"""Check the exact diagnostic LED logic extracted from the generated host."""
import json
from pathlib import Path
import shlex
import subprocess
from prepare import HERE, WORK, sha


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def main():
    source = WORK / 'MacLC_IIe.sv'
    text = source.read_text(encoding='utf-8')
    start = text.index('    wire iie_diagnostic_boundary, iie_diagnostic_fault;')
    end = text.index('dio_download || (disk_act ^ |diskMotor);', start)
    block = text[start:end + len('dio_download || (disk_act ^ |diskMotor);')]
    bench = '''`timescale 1ns/1ps
module tb_led;
    reg clk_sys = 0, pll_locked = 1, dio_download = 0, disk_act = 0;
    reg [1:0] diskMotor = 0;
    reg boundary_input = 0, fault_input = 0;
    wire LED_USER;
    always #5 clk_sys = !clk_sys;
    assign iie_diagnostic_boundary = boundary_input;
    assign iie_diagnostic_fault = fault_input;
''' + block + '''
    initial begin
        @(negedge clk_sys);
        if (LED_USER || iie_diagnostic_ticks != 0) $fatal(1, "idle LED/counter");
        dio_download = 1; #1;
        if (!LED_USER) $fatal(1, "download LED");
        dio_download = 0; disk_act = 1; #1;
        if (!LED_USER) $fatal(1, "disk LED");
        boundary_input = 1; iie_diagnostic_ticks = 25'h1000000; #1;
        if (!LED_USER) $fatal(1, "boundary slow blink");
        fault_input = 1; #1;
        if (LED_USER) $fatal(1, "fault priority");
        iie_diagnostic_ticks = 25'h0200000; #1;
        if (!LED_USER) $fatal(1, "fault fast blink");
        fault_input = 0; #1;
        if (LED_USER) $fatal(1, "boundary override");
        boundary_input = 0;
        @(posedge clk_sys); #1;
        if (iie_diagnostic_ticks != 0) $fatal(1, "inactive reset");
        boundary_input = 1; iie_diagnostic_ticks = 25'h1ffffff; pll_locked = 0;
        @(posedge clk_sys); #1;
        if (iie_diagnostic_ticks != 0) $fatal(1, "PLL reset");
        $display("PASS extracted LED logic: activity, boundary, fault priority, inactive/PLL reset");
        $finish;
    end
endmodule
'''
    path, target = WORK / 'tb_led.sv', WORK / 'led.vvp'
    path.write_text(bench, encoding='ascii')
    outputs = []
    for args in (['iverilog', '-g2012', '-s', 'tb_led', '-o', linux(target), linux(path)], ['vvp', linux(target)]):
        result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)], capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
        outputs.append(result.stdout.strip())
    assert outputs[-1].startswith('PASS ')
    (HERE / 'led-results.json').write_text(json.dumps({'result': outputs[-1],
        'inputs_sha256': {str(p): sha(p) for p in (source, Path(__file__), path)}}, indent=2) + '\n', encoding='ascii')
    print(outputs[-1])


if __name__ == '__main__':
    main()
