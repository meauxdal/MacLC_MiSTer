#!/usr/bin/env python3
"""Bind the isolated IRQ candidate into a separate MacLC hardware project."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MACLC = ROOT.parent / 'MacLC_MiSTer'
BASE = ROOT / 'local/experiments/maclc-iie-build'
WORK = ROOT / 'local/experiments/maclc-iie-irq-build'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    generator = ROOT / 'fixtures/experiments/card-irq-system/prepare.py'
    spec = importlib.util.spec_from_file_location('irq_prepare', generator)
    variant = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(variant)
    cpu, host, card = variant.generate(WORK)
    originals = [ROOT / name for name in variant.PINS]
    substitutes = dict(zip((p.resolve() for p in originals), (card, host, cpu)))
    wrappers = {
        'card-platform/card_platform.sv': (
            '64002ab0ccb5fb08634dae5c7c41bdc9b8f7df20b3804a44ac8d2f0bf3d49d44',
            [('    card_pds_candidate card (', '    card_irq_pds_candidate card (')]),
        'card-pds-system-harness/card_pds_candidate.sv': (
            '30f823ebbac4f4125e4bfa534edf85190962df1c80b010a32911443c21be5ee3',
            [('module card_pds_candidate (', 'module card_irq_pds_candidate ('),
             ('    card_candidate card (', '    card_irq_candidate card (')]),
    }
    for name, (pin, edits) in wrappers.items():
        source = ROOT / 'docs/experiments' / name
        assert sha(source) == pin, name
        text = source.read_text()
        for old, new in edits:
            text = once(text, old, new)
        output = WORK / source.name
        output.write_text(text, encoding='ascii')
        substitutes[source.resolve()] = output
        originals.append(source)
    qip = BASE / 'card_platform.qip'
    closure = [Path(name) for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"', qip.read_text())]
    assert len(closure) == 12 and all(p.is_file() for p in closure)
    closure = [substitutes.get(p.resolve(), p) for p in closure]
    (WORK / 'card_platform.qip').write_text(''.join(
        'set_global_assignment -name SYSTEMVERILOG_FILE "' + p.as_posix() + '"\n' for p in closure), encoding='ascii')
    files = once((BASE / 'files.qip').read_text(), (BASE / 'card_platform.qip').as_posix(),
                 (WORK / 'card_platform.qip').as_posix())
    (WORK / 'files.qip').write_text(files, encoding='ascii')
    source_qsf = MACLC / 'MacLC_IIe.qsf'
    qsf = once(source_qsf.read_text(encoding='utf-8'), (BASE / 'files.qip').as_posix(), (WORK / 'files.qip').as_posix())
    qsf = once(qsf, 'PROJECT_OUTPUT_DIRECTORY output_files/IIe', 'PROJECT_OUTPUT_DIRECTORY output_files/IIe_IRQ')
    for name, data in [('MacLC_IIe_IRQ.qsf', qsf),
                       ('MacLC_IIe_IRQ.qpf', 'QUARTUS_VERSION = "17.0"\nPROJECT_REVISION = "MacLC_IIe_IRQ"\n')]:
        target = MACLC / name
        saved = WORK / name
        if target.exists():
            assert saved.exists() and target.read_bytes() == saved.read_bytes(), 'independently changed project: ' + name
        target.write_text(data, encoding='utf-8')
        saved.write_bytes(target.read_bytes())
    inputs = [Path(__file__), generator, *originals, qip, BASE / 'files.qip', source_qsf,
              ROOT / 'fixtures/experiments/maclc-iie-build/maclc_iie_binding.sv', BASE / 'MacLC_IIe.sv', BASE / 'sdram.v']
    result = {'project': str(MACLC / 'MacLC_IIe_IRQ.qpf'), 'boundary': '203A before JSR2058',
              'full_quartus_build_run': False,
              'inputs_sha256': {str(p): sha(p) for p in inputs},
              'generated_sha256': {str(p): sha(p) for p in [*substitutes.values(), WORK / 'card_platform.qip',
                  WORK / 'files.qip', MACLC / 'MacLC_IIe_IRQ.qsf', MACLC / 'MacLC_IIe_IRQ.qpf']}}
    (HERE / 'project-results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS separate MacLC_IIe_IRQ project generated; original project preserved', flush=True)
    return closure


if __name__ == '__main__':
    prepare()
