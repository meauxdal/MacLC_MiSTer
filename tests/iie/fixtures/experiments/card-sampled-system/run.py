#!/usr/bin/env python3
"""Sampled CPU, PDS and native-SDRAM regression through original softswitch tests."""
import json
from pathlib import Path
import shlex
import subprocess
from prepare import HERE, ROOT, BASE, WORK, once, prepare, sha


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    closure, manifest, inputs = prepare()
    frozen_bench = BASE / 'tb_binding.sv'
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (frozen_bench, binding, controller):
        assert sha(path) == manifest['inputs_sha256'][str(path)], 'changed frozen input: ' + str(path)
    bench = once(frozen_bench.read_text(), 'module tb_card_platform;',
                 'module tb_card_platform #(parameter FAST = 0);\n'
                 '    defparam dut.platform.card.card.PACE_FAST = FAST;')
    bench = once(bench, '    task transact;', '''    reg poll_empty = 0;
    integer extra_status_polls = 0;
    task transact_once;''')
    bench = once(bench, '            if (write_arg == 0 && pds_read_data !== expected_data)', '''            poll_empty = write_arg == 0 && word_arg == 0 && offset_arg == 1 &&
                         value_arg != 0 && pds_read_data === 16'hFF00;
            if (poll_empty) expected_data = 16'hFF00;
            if (write_arg == 0 && pds_read_data !== expected_data)''')
    bench = once(bench, '    task unclaimed(input [31:0] a, input [2:0] fc);', '''    task transact;
        input integer write_arg, word_arg, offset_arg, value_arg, gap_arg;
        integer polls;
        begin
            transact_once(write_arg, word_arg, offset_arg, value_arg, gap_arg);
            polls = 0;
            while (poll_empty) begin
                if (polls == 1001) $fatal(1, "status polling timeout");
                polls = polls + 1;
                extra_status_polls = extra_status_polls + 1;
                transact_once(write_arg, word_arg, offset_arg, value_arg, 1);
            end
        end
    endtask

    task unclaimed(input [31:0] a, input [2:0] fc);''')
    bench = once(bench, '    integer nmis = 0, irqs = 0, rtis = 0, opcodes = 0;', '''    wire cpu_ready = dut.platform.card.card.cpu_ready;
    wire cpu_valid = dut.platform.card.card.cpu_valid;
    wire pace_due = dut.platform.card.card.pace_due;
    wire cpu_wait = dut.platform.card.card.cpu_memory_wait;
    wire cpu_response = dut.platform.card.card.master_rsp_valid[1];
    wire cpu_response_ready = dut.platform.card.card.master_rsp_ready[1];
    integer pace_ticks = 0, last_complete = -1, min_gap = 1000000;
    integer held_responses = 0, early_responses = 0, paced_completions = 0;
    integer cpu_requests = 0, cpu_responses = 0, softswitch_completions = 0, spacing;
    reg bus_held = 0, response_held = 0;
    reg [44:0] saved_bus;
    reg [16:0] saved_response;
    wire [44:0] cpu_bus = {card_cpu_address, dut.platform.card.card.ram_address,
                           dut.platform.card.card.cpu_wdata, dut.platform.card.card.cpu_write,
                           dut.platform.card.card.cpu_sync, dut.platform.card.card.vector_pull,
                           dut.platform.card.card.high_read};
    wire [16:0] cpu_response_bundle = {dut.platform.card.card.master_rdata,
                                      dut.platform.card.card.denied};
    always @(posedge clk_sys) begin
        pace_ticks = pace_ticks + 1;
        if (!dut.platform.card.card.por_n || !dut.platform.card.card.cpu_running) begin
            last_complete = -1;
            bus_held = 0;
            response_held = 0;
        end else begin
            if (bus_held && saved_bus !== cpu_bus)
                $fatal(1, "CPU bus changed before paced completion");
            saved_bus = cpu_bus;
            bus_held = cpu_valid && !cpu_ready;
            if (response_held && (!cpu_response || saved_response !== cpu_response_bundle))
                $fatal(1, "CPU memory response changed under pacing backpressure");
            saved_response = cpu_response_bundle;
            response_held = cpu_wait && cpu_response && !cpu_response_ready;
            if (response_held) held_responses = held_responses + 1;
            if (cpu_wait && cpu_response && !pace_due) early_responses = early_responses + 1;
            if (cpu_response && cpu_response_ready) cpu_responses = cpu_responses + 1;
            if (dut.platform.card.card.master_valid[1] && dut.platform.card.card.master_ready[1])
                cpu_requests = cpu_requests + 1;
            if (cpu_ready) begin
                if (!pace_due) $fatal(1, "CPU completion bypassed pacer");
                paced_completions = paced_completions + 1;
                if (dut.platform.card.card.display_switch) softswitch_completions = softswitch_completions + 1;
                if (last_complete >= 0) begin
                    spacing = pace_ticks - last_complete;
                    if (spacing < (FAST ? 17 : 31)) $fatal(1, "CPU catch-up spacing=%0d", spacing);
                    if (spacing < min_gap) min_gap = spacing;
                end
                last_complete = pace_ticks;
            end
        end
    end
    integer sampled_waits = 0, sampled_traps = 0;
    always @(posedge clk_sys) begin
        if (dut.platform.card.card.cpu_running && pace_due) begin
            if (!cpu_ready) sampled_waits = sampled_waits + 1;
            if (dut.platform.card.card.capture_valid && !cpu_ready) sampled_traps = sampled_traps + 1;
        end
        if (dut.platform.card.card.processor.cpu.ce !== pace_due)
            $fatal(1, "CPU pin sampling lost pacing tick");
        if (dut.platform.card.card.processor.cpu.rdy !==
            (dut.platform.card.card.processor.waiting || cpu_ready))
            $fatal(1, "CPU RDY differs from completion/WAI policy");
    end
    integer nmis = 0, irqs = 0, rtis = 0, opcodes = 0;''')
    bench = once(bench, '        $fclose(stimulus);', '''        if (cpu_requests != cpu_responses || paced_completions != cpu_completed ||
            softswitch_completions != 16 || held_responses == 0 || early_responses == 0)
            $fatal(1, "paced coverage/completion counts requests=%0d responses=%0d completed=%0d/%0d switches=%0d held=%0d early=%0d",
                   cpu_requests, cpu_responses, paced_completions, cpu_completed,
                   softswitch_completions, held_responses, early_responses);
        $display("PACE fast=%0d min_gap=%0d completions=%0d CPU_mem=%0d held_response_ticks=%0d early_response_ticks=%0d softswitches=%0d extra_status_polls=%0d",
                 FAST, min_gap, paced_completions, cpu_requests, held_responses, early_responses, softswitch_completions, extra_status_polls);
        if (sampled_waits == 0 || sampled_traps == 0)
            $fatal(1, "missing sampling during backend/host waits");
        $display("SAMPLE waits=%0d traps=%0d", sampled_waits, sampled_traps);
        $fclose(stimulus);''')
    bench_path = WORK / 'tb_binding.sv'
    bench_path.write_text(bench, encoding='ascii')
    sources = [bench_path, binding, *closure, controller]
    runs = []
    inputs += [Path(__file__), HERE / 'prepare.py', frozen_bench, *sources]
    for fast in (0, 1):
        executable = WORK / f'paced-{fast}.vvp'
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
             f'-Ptb_card_platform.FAST={fast}', '-o', linux(executable), *map(linux, sources)])
        for fork in (0, 1):
            stimulus, image = BASE / f'stimulus{fork}.txt', BASE / f'expected{fork}.hex'
            prefix = ROOT / f'local/experiments/maclc-iie-banking-build/stimulus{fork}.txt'
            old_image = ROOT / f'local/experiments/maclc-iie-banking-build/expected{fork}.hex'
            for path in (prefix, old_image):
                assert sha(path) == manifest['inputs_sha256'][str(path)], 'changed frozen data: ' + str(path)
            on = (0xC00F, 0xC051, 0xC057, 0xC05F, 0xC00D, 0xC053, 0xC055, 0xC001)
            tail = []
            for index, address in enumerate(on + tuple(address - 1 for address in on)):
                state = (1 << (index + 1)) - 1 if index < 8 else 255 ^ ((1 << (index - 7)) - 1)
                tail += [(0, 0, 1, 8), (0, 0, 1, 8), (0, 1, 4, address),
                         (0, 0, 8, state), (0, 0, 8, state), (1, 0, 12, 0)]
            assert stimulus.read_text() == prefix.read_text() + ''.join(
                f'{write} {word} {offset} {value} 2000\n' for write, word, offset, value in tail)
            expected = [int(value, 16) for value in old_image.read_text().split()]
            assert len(expected) == 262144 and expected[0x1FC] == 0x3F
            expected[0x1FC] = 0x42
            assert [int(value, 16) for value in image.read_text().split()] == expected
            inputs += [stimulus, image, prefix, old_image]
            for phase in (2, 7):
                trace = WORK / f'captures-{fast}-{fork}-{phase}.txt'
                output, errors = wsl(['vvp', linux(executable), '+stimulus=' + linux(stimulus),
                                      '+expected=' + linux(image), '+trace=' + linux(trace), f'+sys_phase={phase}'])
                assert not errors and 'PASS PDS=' in output and 'PACE fast=' in output, output + errors
                assert sha(trace) == manifest['runs'][fork * 2]['capture_sha256'], 'capture trace changed'
                print(output, flush=True)
                runs.append({'fast': fast, 'fork': fork, 'phase_ns': phase,
                             'result': output, 'capture_sha256': sha(trace)})
    _, warnings = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                       '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                       'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert '%Warning' not in warnings, warnings
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'independent CPU sampling with paced PDS/native-SDRAM service; no hardware timing claim',
        'cpu_clock_hz': 32500000, 'memory_clock_hz': 65000000,
        'rates_hz': [1020000, 1900000], 'boundary': '2043', 'runs': runs,
        'memory_bytes_compared_per_run': 262144,
        'lint': 'binding/card -Wall passes with existing filename/unused/unconnected exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
