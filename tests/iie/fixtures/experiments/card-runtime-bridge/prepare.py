#!/usr/bin/env python3
"""Bind the pinned monitor continuation to externally executed host requests."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-runtime-bridge'
PARENT = ROOT / 'local/experiments/card-monitor-resume'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare():
    pins_path = ROOT / 'fixtures/experiments/card-monitor-resume/results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [Path(p) for p in names[names.index(str(binding)):] if Path(p).suffix in ('.v', '.sv')]
    sources.append(ROOT / 'fixtures/experiments/card-cpu-pacing/card_cycle_pacer.sv')
    original, image = PARENT / 'tb_monitor.sv', PARENT / 'initial.hex'
    for path in [original, image, *sources]:
        assert sha(path) == pins[str(path)], 'changed pinned source: ' + str(path)
    WORK.mkdir(parents=True, exist_ok=True)
    text = original.read_text()
    text = once(text, '    reg poll_empty = 0;', '''    reg bridge_active = 0;
    integer bridge_reply, bridge_sequence, bridge_write, bridge_width, bridge_offset, bridge_value;
    integer bridge_fields, bridge_index;
    reg poll_empty = 0;''')
    text = once(text, '            poll_empty = write_arg == 0', '''            if (bridge_active) begin
                expected_data = pds_read_data;
                bridge_reply = write_arg != 0 ? value_arg : word_arg != 0 ?
                    {16'b0, pds_read_data} : offset_arg[0] ?
                    {24'b0, pds_read_data[7:0]} : {24'b0, pds_read_data[15:8]};
            end
            poll_empty = !bridge_active && write_arg == 0''')
    text = once(text, '''        transact(0, 0, 12, service_id, 0);
        transact(1, 0, 12, 0, 0);''', '''        bridge_active = 1;
        $display("READY");
        $fflush();
        for (bridge_index = 1; bridge_index <= 5; bridge_index = bridge_index + 1) begin
            bridge_fields = $fscanf(32'h80000000, "%d %d %d %d %d",
                bridge_sequence, bridge_write, bridge_width, bridge_offset, bridge_value);
            if (bridge_fields != 5 || bridge_sequence != bridge_index ||
                (bridge_write != 0 && bridge_write != 1) ||
                (bridge_width != 8 && bridge_width != 16)) $fatal(1, "invalid bridge request");
            transact(bridge_write, bridge_width == 16, bridge_offset, bridge_value, 0);
            $display("REPLY %0d %0d", bridge_sequence, bridge_reply);
            $fflush();
        end
        bridge_active = 0;
        repeat (20) @(negedge clk_sys);
        if (capture_valid) $fatal(1, "runtime host ACK did not release service capture");''')
    bench = WORK / 'tb_bridge.sv'
    bench.write_text(text, encoding='ascii')
    host_source = ROOT / 'fixtures/experiments/card-runtime-dispatch/execute.lua'
    host_pins = ROOT / 'fixtures/experiments/card-runtime-dispatch/results.json'
    assert sha(host_source) == json.loads(host_pins.read_text())['inputs_sha256'][str(host_source.relative_to(ROOT))]
    host = once(host_source.read_text(), 'local frames, ack = 0, false',
                "local bridge = dofile('fixtures/experiments/card-runtime-bridge/bridge.lua')\nlocal frames, ack = 0, false")
    host = once(host, '''            if off == 1 and count == 1 then result = ack and 0 or 0xe0
            elseif off == 4 and count == 2 then result = 0xc07d
            elseif off == 0xc and count == 1 then result = service
            else error(string.format('Unexpected read %x/%d', off, count)) end''',
                '''            if ack then
                assert(off == 1 and count == 1, 'Unexpected post-ACK read')
            else
                result = bridge(false, count * 8, off, 0)
            end''')
    host = once(host, "            ack = true", "            bridge(true, 8, 12, 0)\n            ack = true")
    (WORK / 'execute.lua').write_text(host, encoding='ascii')
    return [bench, *sources], image, [pins_path, original, image, *sources, HERE / 'prepare.py',
                                    host_source, host_pins, WORK / 'execute.lua', HERE / 'bridge.lua']


if __name__ == '__main__':
    prepare()
