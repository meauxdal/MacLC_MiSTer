#!/usr/bin/env python3
"""Record the existing MacLC branch sources without generating a project."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MACLC = ROOT.parents[1]
WORK = ROOT / 'local/experiments/maclc-iie-runtime'
RTL = MACLC / 'rtl'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset_path(name):
    """Resolve recorded Windows or WSL asset paths within this test checkout."""
    name = str(name).replace('\\', '/')
    for prefix in ('C:/Workspace/Git/Apple-IIe-Card/', '/mnt/c/Workspace/Git/Apple-IIe-Card/',
                   'C:/Workspace/Git/MacLC_MiSTer/tests/iie/', '/mnt/c/Workspace/Git/MacLC_MiSTer/tests/iie/'):
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):]
            if name.startswith('docs/'):
                name = 'fixtures/' + name[5:]
            return ROOT / name
    return Path(name)


def runtime_sources():
    WORK.mkdir(parents=True, exist_ok=True)
    names = re.findall(r'-name SYSTEMVERILOG_FILE (.+)', (MACLC / 'files.qip').read_text())
    sources = [MACLC / name.strip('"') for name in names]
    sources = [p for p in sources if p.name.startswith('card_') or
               p.name in ('cpu_65c02.sv', 'cpu_alu.sv')]
    assert sources and all(p.is_file() for p in sources), 'Missing MacLC card sources'
    return sources


def prepare():
    sources = runtime_sources()
    inputs = [MACLC / name for name in ('MacLC.qpf', 'MacLC.qsf', 'MacLC.sdc',
                                       'MacLC.sv', 'files.qip')]
    for kind, name in re.findall(r'-name (\w+_FILE) (.+)', (MACLC / 'files.qip').read_text()):
        path = MACLC / name.strip('"')
        assert path.is_file(), f'Missing {kind}: {path}'
        inputs.append(path)
    # Conservatively invalidate fit results after any host RTL or sys change.
    for directory in ('rtl', 'sys'):
        inputs.extend(p for p in (MACLC / directory).rglob('*') if p.is_file() and
                      p.suffix.lower() in ('.v', '.sv', '.vh', '.vhd', '.qip', '.tcl', '.sdc', '.mif', '.hex'))
    inputs = list(dict.fromkeys(inputs))
    manifest = {'project': str(MACLC / 'MacLC.qpf'), 'build_run': False,
                'sha256': {str(p): sha(p) for p in inputs}}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')
    print(manifest['project'])
    return sources


if __name__ == '__main__':
    prepare()
