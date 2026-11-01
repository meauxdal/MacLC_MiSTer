#!/usr/bin/env python3
"""Run original monitor through first return to its next service boundary."""
import argparse
import hashlib
import json
import shlex
import subprocess
from prepare import HERE, ROOT, PARENT, BASE_WORK, WORK, once, prepare, sha


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fast', type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    closure, inputs = prepare()
    metadata = ROOT / 'fixtures/experiments/firmware-memory/metadata.json'
    resources = json.loads(metadata.read_text())['resources']
    slot_pins = ROOT / 'fixtures/experiments/card-slot3-recovery/results.json'
    slot_evidence = json.loads(slot_pins.read_text())
    for name, digest in slot_evidence['inputs_sha256'].items():
        path = ROOT / name
        assert sha(path) == digest, 'changed slot3 evidence: ' + name
        inputs.append(path)
    fill = b'\x00\xea' * (0xC000 // 2)
    assert hashlib.sha256(fill).hexdigest() == slot_evidence['host_initial_fill']['sha256']
    image = bytearray(262144)
    image[0x24000:0x30000] = fill
    for resource_id, address in ((2606, 0x20000), (2607, 0x25000), (2611, 0x27FFA)):
        entry = next(item for item in resources if item['type'] == 'Monx' and item['id'] == resource_id)
        payload = ROOT / f'local/experiments/firmware-memory/decoded/Monx_{resource_id}.payload.bin'
        assert sha(payload) == entry['payload_sha256'] and payload.stat().st_size == entry['count']
        image[address:address + entry['count']] = payload.read_bytes()
        inputs.append(payload)
    image_path = WORK / 'initial.hex'
    image_path.write_text(''.join(f'{value:02x}\n' for value in image), encoding='ascii')
    original = BASE_WORK / 'tb_monitor.sv'
    pins_path = PARENT / 'results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (original, binding, controller):
        assert sha(path) == pins[str(path)], 'changed source: ' + str(path)
    text = once(original.read_text(), 'ticks > 200000', 'ticks > 2000000')
    marker = '    integer service_writes = 0, ram_writes = 0, service_pc = -1, service_id = -1;'
    assert text.count(marker) == 1
    prefix, tail = text.split(marker)
    _, primitive = tail.split('\nmodule altddio_out ', 1)
    sequence = HERE / 'monitor_sequence.sv'
    bench = WORK / 'tb_monitor.sv'
    bench.write_text(prefix + sequence.read_text() + '\nendmodule\n\nmodule altddio_out ' + primitive,
                     encoding='ascii')
    sources = [bench, binding, *closure, controller]
    binary = WORK / f'monitor-{args.fast}.vvp'
    wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
         f'-Ptb_card_platform.FAST={args.fast}', '-o', linux(binary), *map(linux, sources)])
    runs = []
    for phase in (2, 7):
        trace = WORK / f'captures-{args.fast}-{phase}.txt'
        instructions = WORK / f'instructions-{args.fast}-{phase}.txt'
        try:
            output, errors = wsl(['vvp', linux(binary), '+trace=' + linux(trace),
                                  '+image=' + linux(image_path), '+instructions=' + linux(instructions),
                                  f'+sys_phase={phase}'])
        except AssertionError:
            if instructions.is_file():
                print('\n'.join(instructions.read_text().splitlines()[-16:]), flush=True)
            raise
        assert 'PASS monitor' in output and not errors, output + errors
        assert instructions.read_text().splitlines()[0].startswith('fa62 d8 '), 'wrong normal reset entry'
        print(output, flush=True)
        runs.append({'fast': args.fast, 'phase_ns': phase, 'result': output,
                     'capture_sha256': sha(trace), 'instructions_sha256': sha(instructions)})
    _, lint = wsl(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
                   '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
                   'maclc_iie_binding', linux(binding), *map(linux, closure)])
    assert not lint, lint
    inputs += [metadata, pins_path, slot_pins, HERE / 'run.py', sequence, original, image_path, *sources]
    (HERE / f'results-{args.fast}.json').write_text(json.dumps({
        'scope': 'monitor after first harness-acknowledged service; selected Cx and original slot3 fill; candidate physical routing',
        'runs': runs, 'memory_transport_bytes_compared': 262144,
        'independent_text_bytes_compared': 1920,
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
