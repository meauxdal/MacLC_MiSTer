#!/usr/bin/env python3
"""Inspect existing disk implementations and qualify original IWM register test."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-iwm'
CPU = ROOT / 'fixtures/experiments/card-cpu-rtl'
sys.path.insert(0, str(ROOT / 'fixtures/experiments/host-harness'))
from host_model import HostStream, Hypothesis, conf_uploads, load_conf_resources


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip(), result.stderr.strip()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    source_dir = WORK / 'source'
    source_dir.mkdir(exist_ok=True)
    baseline = json.loads((CPU / 'results.json').read_text())
    archive = ROOT / 'local/Apple-II_MiSTer/Apple-II_MiSTer-master.zip'
    pins = baseline['inputs_sha256']
    assert sha(archive) == pins[archive.relative_to(ROOT).as_posix()]
    with zipfile.ZipFile(archive) as zipped:
        inventory = [name for name in zipped.namelist() if any(word in name.lower() for word in ('iwm', 'disk', 'woz'))]
        for name in ('disk_ii_woz.sv', 'flux_drive.v', 'woz_floppy_controller.sv'):
            target = source_dir / name
            target.write_bytes(zipped.read('Apple-II_MiSTer-master/rtl/woz/' + name))
    disk = (source_dir / 'disk_ii_woz.sv').read_text()
    assert '.IWM_MODE(5\'b00000)' in disk and 'assign D_OUT = IO_SELECT ? rom_dout : data_reg_vis;' in disk
    swim = ROOT.parents[1] / 'rtl/swim.v'
    assert 'reg [4:0] iwmMode;' in swim.read_text()
    inputs = [Path(__file__), CPU / 'results.json', archive, swim,
              HERE / 'card_iwm_frontend.sv', HERE / 'tb_iwm.sv', HERE / 'tb_diagnostic.sv',
              *source_dir.glob('*')]
    cpu_sources = [CPU / 'card_cpu_bus.sv', ROOT / 'local/experiments/card-cpu-rtl/source/cpu_65c02.sv',
                   ROOT / 'local/experiments/card-cpu-rtl/source/cpu_alu.sv']
    for path in cpu_sources:
        key = path.relative_to(ROOT).as_posix() if path.parent == CPU else 'archive:rtl/cpu/wdc65c02/' + path.name
        assert sha(path) == pins[key], 'changed frozen CPU source'
    inputs += cpu_sources
    sources = [HERE / 'card_iwm_frontend.sv', *cpu_sources]
    unit_binary = WORK / 'iwm.vvp'
    wsl(['iverilog', '-g2012', '-s', 'tb_iwm', '-o', linux(unit_binary),
         linux(HERE / 'tb_iwm.sv'), linux(sources[0])])
    unit_result, errors = wsl(['vvp', linux(unit_binary)])
    assert unit_result.startswith('PASS ') and not errors, unit_result + errors
    print(unit_result, flush=True)
    executable = WORK / 'diagnostic.vvp'
    wsl(['iverilog', '-g2012', '-s', 'tb_diagnostic', '-o', linux(executable),
         linux(HERE / 'tb_diagnostic.sv'), *map(linux, sources)])
    original = bytes.fromhex('a2812ceec02cecc02ce0c02ce2c02ce4c02ce6c02ce8c0a91f2cedc08defc04deec0291fd00ea9008defc04deec0291fd002a20060')
    expected_io = [(0xC0EE, 0), (0xC0EC, 0), (0xC0E0, 0), (0xC0E2, 0), (0xC0E4, 0),
                   (0xC0E6, 0), (0xC0E8, 0), (0xC0ED, 0), (0xC0EF, 1),
                   (0xC0EE, 0), (0xC0EF, 1), (0xC0EE, 0)]
    runs = []
    evidence = []
    for fork in (0, 1):
        resource = ROOT / ('local/experiments/startup-runtime/startup/IIe Startup.rsrc' if fork
                           else 'local/experiments/firmware-memory/app221/IIe Startup.rsrc')
        assert sha(resource) == pins[resource.relative_to(ROOT).as_posix()]
        resources = load_conf_resources(resource)
        assert resources[1001][6 + 0x163:6 + 0x198] == original
        stream = HostStream(Hypothesis('iwm-register-test'), lambda offset, width: 0)
        assert conf_uploads(stream, resources) == 0
        assert stream.memory[0x2163:0x2198] == original
        image = WORK / f'image{fork}.hex'
        image.write_text(''.join(f'{value:02x}\n' for value in stream.memory), encoding='ascii')
        inputs += [resource, image]
        evidence.append({'fork_sha256': sha(resource), 'diagnostic_2163_2198_sha256': hashlib.sha256(original).hexdigest()})
        for delay in (0, 1):
            trace = WORK / f'io-{fork}-{delay}.txt'
            output, errors = wsl(['vvp', linux(executable), '+image=' + linux(image),
                                  '+trace=' + linux(trace), f'+delay={delay}'])
            assert output.startswith('PASS ') and not errors, output + errors
            rows = [tuple(int(value, 16) for value in row.split()) for row in trace.read_text().splitlines()]
            assert [(address, write) for address, write, _, _ in rows] == expected_io, rows
            assert [rows[index][3] & 31 for index in (9, 11)] == [31, 0], rows
            assert [rows[index][2] for index in (8, 10)] == [31, 0], rows
            print(output, flush=True)
            runs.append({'fork': fork, 'delay': delay, 'result': output, 'io_sha256': sha(trace)})
    controls = []
    for name, replacement in [('frozen_mode', "5'b0"), ('stuck_bit', "write_data[4:0] & 5'h0F")]:
        broken = WORK / f'{name}.sv'
        code = sources[0].read_text()
        assert code.count('mode <= write_data[4:0];') == 1
        broken.write_text(code.replace('mode <= write_data[4:0];', f'mode <= {replacement};'), encoding='ascii')
        binary = WORK / f'{name}.vvp'
        wsl(['iverilog', '-g2012', '-s', 'tb_diagnostic', '-o', linux(binary),
             linux(HERE / 'tb_diagnostic.sv'), linux(broken), *map(linux, cpu_sources)])
        args = ['vvp', linux(binary), '+image=' + linux(WORK / 'image0.hex'),
                '+trace=' + linux(WORK / f'{name}.txt'), '+delay=1']
        result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'original IWM diagnostic failed X=81' in result.stdout and not result.stderr, result.stdout + result.stderr
        controls.append({'fault': name, 'result': result.stdout.strip()})
        print('PASS ' + name + ' rejected by original diagnostic', flush=True)
    _, warnings = wsl(['verilator', '--lint-only', '-Wall', '--top-module', 'card_iwm_frontend', linux(sources[0])])
    assert not warnings, warnings
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'IWM register frontend; actual CPU original subroutine; no flux/media implementation claim',
        'archive_disk_inventory': inventory, 'original_spans': evidence, 'unit_result': unit_result,
        'runs': runs, 'negative_controls': controls, 'memory_bytes_compared_per_run': 262144,
        'lint': 'frontend Verilator -Wall passes without exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
