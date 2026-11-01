#!/usr/bin/env python3
"""Execute original ALTCHAR-off service for the monitor's held C00E write."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-first-switch'


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
                "assign boundary = capture_valid && capture_address == 16'hC001;")
    candidate.write_text(text, encoding='ascii')
    sources = [candidate if path == card else path for path in sources]
    host_source = ROOT / 'local/experiments/card-runtime-bridge/execute.lua'
    assert sha(host_source) == json.loads((ROOT / 'fixtures/experiments/card-runtime-bridge/results.json').read_text())['inputs_sha256'][str(host_source)]
    host = once(host_source.read_text(), "dofile('fixtures/experiments/card-runtime-bridge/bridge.lua')",
                "dofile('fixtures/experiments/card-first-switch/bridge.lua')")
    host = once(host, "        cpu.state['PC'].value = base + 0x281c", """        machine.debugger:command('temp0=0')
        cpu.debug:bpset(base + 0x1630, '1', 'temp0=1; g')
        local save = 'save "' .. run .. '/world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'printf "SWITCH_RETURN pc=%08X sp=%08X",pc,a7; trace off,:maincpu; quit'
        cpu.debug:bpset(base + 0x281c, 'temp0==1', save)
        cpu.debug:bpset(base + 0xb10, '1', 'save "' .. run .. '/wrong-route.bin",2fa6a0,5c49; trace off,:maincpu; quit')
        cpu.state['PC'].value = base + 0x281c""")
    host = once(host, '    elseif frames == 3001 then', """    elseif frames == 3001 then
        local snapshot = assert(io.open(run .. '/world.bin', 'rb') or
            io.open(run .. '/wrong-route.bin', 'rb'), 'Switch return not reached')
        snapshot:close()""")
    (WORK / 'execute.lua').write_text(host, encoding='ascii')
    image = ROOT / 'local/experiments/card-monitor-resume/initial.hex'
    return [bench, *sources], image, [pins_path, original, card, host_source, sequence, image,
                                    HERE / 'prepare.py', HERE / 'bridge.lua', WORK / 'execute.lua']
