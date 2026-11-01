#!/usr/bin/env python3
"""Run original normal monitor reset through its first NMI service and return."""
import argparse
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
    image = bytearray(262144)
    for resource_id, address in ((2606, 0x20000), (2607, 0x25000), (2611, 0x27FFA)):
        entry = next(item for item in resources if item['type'] == 'Monx' and item['id'] == resource_id)
        payload = ROOT / f'local/experiments/firmware-memory/decoded/Monx_{resource_id}.payload.bin'
        assert sha(payload) == entry['payload_sha256'] and payload.stat().st_size == entry['count']
        image[address:address + entry['count']] = payload.read_bytes()
        inputs.append(payload)
    image_path = WORK / 'initial.hex'
    image_path.write_text(''.join(f'{value:02x}\n' for value in image), encoding='ascii')
    original = BASE_WORK / 'tb_binding.sv'
    pins_path = PARENT / 'regression-1-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    for path in (original, binding, controller):
        assert sha(path) == pins[str(path)], 'changed source: ' + str(path)
    text = once(original.read_text(), 'ticks > 2000000', 'ticks > 200000')
    marker = '    initial begin\n        if (!$value$plusargs("stimulus=%s", stimulus_path))'
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
    inputs += [metadata, pins_path, HERE / 'run.py', sequence, original, image_path, *sources]
    (HERE / f'results-{args.fast}.json').write_text(json.dumps({
        'scope': 'original monitor reset and first service; candidate ROM mapping, preloaded firmware snapshot',
        'runs': runs, 'memory_transport_bytes_compared': 262144,
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
