#!/usr/bin/env python3
"""Bounded loader/arbiter/controller composition; each tool has a 30s limit."""
import hashlib
import json
import shlex
import subprocess
from pathlib import Path
from prepare import HERE, ROOT, WORK, MACLC, PIN, prepare


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args, failure=None):
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(args)], capture_output=True, text=True, timeout=30)
    output = result.stdout.strip()
    if failure:
        assert result.returncode and failure in output, output + result.stderr
    else:
        assert result.returncode == 0, output + result.stderr
    return output, result.stderr.strip()


def main():
    download = prepare()
    sources = [HERE / 'tb_loader.sv', HERE / 'loader_admission.sv', WORK / 'loader.sv',
               download / 'maclc_download.sv', download / 'sdram.v',
               HERE.parent / 'card-quiesce/card_warm_reset.sv']
    inputs = [*sources, HERE / 'prepare.py', HERE / 'run.py',
              HERE.parent / 'maclc-download-quiesce/prepare.py', HERE.parent / 'card-quiesce/prepare.py',
              MACLC / 'rtl/floppy_sd.v', MACLC / 'MacLC.sv', MACLC / 'rtl/sdram.v']
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    runs = []
    cases = [('loader', None, None),
             ('raw-mount', 'UNSAFE_RAW_MOUNT', 'active mount metadata overwritten'),
             ('live-base', 'UNSAFE_LIVE_BASE', 'write outside retained allocation'),
             ('word-idle', 'UNSAFE_WORD_IDLE_STOP', 'reinit before whole loader drain'),
             ('release-ack', 'UNSAFE_RELEASE_ACK', 'reinit before whole loader drain')]
    for name, define, failure in cases:
        binary = WORK / (name + '.vvp')
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', *(['-D' + define] if define else []),
             '-s', 'tb_loader', '-o', linux(binary), *map(linux, sources)])
        for phase in ((2, 7) if not failure else (2,)):
            output, errors = wsl(['vvp', linux(binary), '+PHASE=' + str(phase)], failure)
            assert not errors, errors
            assert failure or 'PASS loader' in output, output
            print(output, flush=True)
            runs.append({'name': name, 'phase_ns': phase, 'expected_failure': failure, 'result': output})
            (WORK / (name + '-' + str(phase) + '.log')).write_text(output + '\n', encoding='ascii')
    out, err = wsl(['verilator', '--lint-only', '--timing', '-Wno-fatal', '-Wno-PINMISSING',
                    '-DTB_NO_TRISTATE', '--top-module', 'tb_loader', *map(linux, sources)])
    warnings = [line for line in err.splitlines() if line.startswith('%Warning')]
    (WORK / 'lint.log').write_text(out + '\n' + err, encoding='ascii')
    assert len(warnings) == 2 and all('sdram.v' in w and 'WIDTHEXPAND' in w for w in warnings), err
    assert hashlib.sha256((MACLC / 'rtl/floppy_sd.v').read_bytes()).hexdigest() == PIN
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in hashes.items()), 'source changed during testing'
    (HERE / 'results.json').write_text(json.dumps({
        'scope': 'real loader behind retained mount admission; tested download arbiter; actual SDRAM controller and warm reset coordinator',
        'sd_service': 'modeled; retains accepted image backing until load completion',
        'hps_fence': 'harness-only contract; transport fence remains unimplemented',
        'deferred_capacity': 'one event; overflow sticky and inhibits stopped; cold reset only',
        'runs': runs, 'lint_warnings': warnings,
        'inputs_sha256': {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace('\\', '/'):
                          hashes[p] for p in inputs},
    }, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
