#!/usr/bin/env python3
"""Execute the monitor's five original Macintosh display-switch handlers."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-display-switches'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare():
    pins_path = ROOT / 'fixtures/experiments/card-display-mask/results.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, 'changed input: ' + name
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [Path(name) for name in names[names.index(str(binding)):] if Path(name).suffix in ('.sv', '.v')]
    WORK.mkdir(parents=True, exist_ok=True)
    original = ROOT / 'local/experiments/card-display-mask/tb_mask.sv'
    text = original.read_text()
    marker = '    initial begin\n        if (!$value$plusargs("image=%s", image_path)'
    prefix, tail = text.split(marker)
    _, primitive = tail.split('\nmodule altddio_out ', 1)
    sequence = HERE / 'sequence.sv'
    bench = WORK / 'tb_switch.sv'
    bench.write_text(prefix + sequence.read_text() + '\nendmodule\nmodule altddio_out ' + primitive, encoding='ascii')
    card = ROOT / 'local/experiments/card-monitor-resume/card_irq_candidate.sv'
    candidate = WORK / card.name
    text = once(card.read_text(), "else if (display_switch) capture_status <= 8'h08;",
                "else if (display_switch) capture_status <= 8'hE0;")
    text = once(text, "assign boundary = monitor_done && cpu_valid && cpu_sync && cpu_address == 16'hFB63;",
                "assign boundary = capture_valid && capture_address == 16'hC07D;")
    candidate.write_text(text, encoding='ascii')
    sources = [candidate if path == card else path for path in sources]
    host_source = ROOT / 'local/experiments/card-runtime-bridge/execute.lua'
    assert sha(host_source) == json.loads((ROOT / 'fixtures/experiments/card-runtime-bridge/results.json').read_text())['inputs_sha256'][str(host_source)]
    host = once(host_source.read_text(), "dofile('fixtures/experiments/card-runtime-bridge/bridge.lua')",
                "dofile('fixtures/experiments/card-display-switches/bridge.lua')")
    host = once(host, "        cpu.state['PC'].value = base + 0x281c", """        machine.debugger:command('temp0=0')
        cpu.debug:bpset(base + 0x1584, '1', 'temp0=1; g')
        local save = 'save "' .. run .. '/world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'printf "SWITCH_RETURN pc=%08X sp=%08X",pc,a7; trace off,:maincpu; quit'
        cpu.debug:bpset(base + 0x281c, 'temp0==1', save)
        cpu.debug:bpset(base + 0xb10, '1', 'save "' .. run .. '/wrong-route.bin",2fa6a0,5c49; trace off,:maincpu; quit')
        cpu.state['PC'].value = base + 0x281c""")
    host = once(host, """            if ack then
                assert(off == 1 and count == 1, 'Unexpected post-ACK read')
            else
                result = bridge(false, count * 8, off, 0)
            end""", "            result = bridge(false, count * 8, off, 0)")
    host = once(host, 'local taps = {}', 'local taps = {}\nlocal polls = 0')
    host = once(host, "'/trace.txt,:maincpu'", "'/trace.txt,:maincpu,noloop'")
    host = once(host, '            result = bridge(false, count * 8, off, 0)', """            if off == 1 and count == 1 then
                polls = polls + 1
                local snapshot = assert(io.open(run .. '/poll-' .. polls .. '.bin', 'wb'))
                snapshot:write(space:read_range(world - 0x5960, world + 0x2e8, 8))
                snapshot:close()
            end
            result = bridge(false, count * 8, off, 0)""")
    host = once(host, "            assert(offset - card == 0xc and mask == 0xff000000 and (data >> 24) == 0, 'Unexpected write')\n            assert(not ack, 'Duplicate ACK')\n            bridge(true, 8, 12, 0)\n            ack = true\n            bus:write('[true,8,12,0]\\n')", """            local off = offset - card
            if mask == 0xff000000 then
                data = (data >> 24) & 0xff
            elseif mask == 0x00ff0000 then
                off = off + 1
                data = (data >> 16) & 0xff
            else
                error('Unexpected write width')
            end
            assert((off == 12 and data == 0) or off == 13, 'Unexpected write')
            bridge(true, 8, off, data)
            ack = ack or off == 12
            bus:write(string.format('[true,8,%d,%d]\\n', off, data))""")
    host = once(host, '    elseif frames == 3001 then', """    elseif frames == 3001 then
        local snapshot = assert(io.open(run .. '/world.bin', 'rb') or
            io.open(run .. '/wrong-route.bin', 'rb'), 'Switch return not reached')
        snapshot:close()""")
    (WORK / 'execute.lua').write_text(host, encoding='ascii')
    image = ROOT / 'local/experiments/card-monitor-resume/initial.hex'
    return [bench, *sources], image, [pins_path, original, card, host_source, sequence, image,
                                    HERE / 'prepare.py', HERE / 'bridge.lua', WORK / 'execute.lua']
