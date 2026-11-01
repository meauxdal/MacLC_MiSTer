#!/usr/bin/env python3
"""Prepare a separate hardware project for bounded banking/protection tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'local/experiments/maclc-iie-irq-build'
WORK = ROOT / 'local/experiments/maclc-iie-banking-build'
MACLC = ROOT.parent / 'MacLC_MiSTer'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def prepare():
    generator = ROOT / 'fixtures/experiments/card-banking-system/prepare.py'
    spec = importlib.util.spec_from_file_location('banking_prepare', generator)
    variant = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(variant)
    generated = variant.generate(WORK)
    qip = BASE / 'card_platform.qip'
    closure = [Path(name) for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"', qip.read_text())]
    assert len(closure) == 12 and all(p.is_file() for p in closure)
    substitutions = {p.name: p for p in generated}
    closure = [substitutions.get(p.name, p) for p in closure]
    files = once((BASE / 'files.qip').read_text(), (BASE / 'card_platform.qip').as_posix(),
                 (WORK / 'card_platform.qip').as_posix())
    binding_source = ROOT / 'fixtures/experiments/maclc-iie-build/maclc_iie_binding.sv'
    binding = once(binding_source.read_text(), '    output wire claim, dtack_n, error,',
                   '    output wire diagnostic_boundary, diagnostic_fault,\n    output wire claim, dtack_n, error,')
    binding = once(binding, '.fault(), .boundary(),', '.fault(diagnostic_fault), .boundary(diagnostic_boundary),')
    binding_path = WORK / 'maclc_iie_binding.sv'
    binding_path.write_text(binding, encoding='ascii')
    host_base = ROOT / 'local/experiments/maclc-iie-build'
    top_source = host_base / 'MacLC_IIe.sv'
    top = once(top_source.read_text(encoding='utf-8'),
               '\tassign LED_USER  = dio_download || (disk_act ^ |diskMotor);', '''    wire iie_diagnostic_boundary, iie_diagnostic_fault;
    reg [24:0] iie_diagnostic_ticks = 0;
    always @(posedge clk_sys) begin
        if (!pll_locked || (!iie_diagnostic_boundary && !iie_diagnostic_fault))
            iie_diagnostic_ticks <= 0;
        else
            iie_diagnostic_ticks <= iie_diagnostic_ticks + 25'd1;
    end
    assign LED_USER = iie_diagnostic_fault ? iie_diagnostic_ticks[21] :
                      iie_diagnostic_boundary ? iie_diagnostic_ticks[24] :
                      dio_download || (disk_act ^ |diskMotor);''')
    top = once(top, '        .claim(iie_card_claim_raw),',
               '        .diagnostic_boundary(iie_diagnostic_boundary), .diagnostic_fault(iie_diagnostic_fault),\n'
               '        .claim(iie_card_claim_raw),')
    top_path = WORK / 'MacLC_IIe.sv'
    top_path.write_text(top, encoding='utf-8')
    files = once(files, binding_source.as_posix(), binding_path.as_posix())
    files = once(files, top_source.as_posix(), top_path.as_posix())
    (WORK / 'card_platform.qip').write_text(''.join(
        'set_global_assignment -name SYSTEMVERILOG_FILE "' + p.as_posix() + '"\n' for p in closure), encoding='ascii')
    (WORK / 'files.qip').write_text(files, encoding='ascii')
    source_qsf = BASE / 'MacLC_IIe_IRQ.qsf'
    qsf = once(source_qsf.read_text(encoding='utf-8'), (BASE / 'files.qip').as_posix(), (WORK / 'files.qip').as_posix())
    qsf = once(qsf, 'PROJECT_OUTPUT_DIRECTORY output_files/IIe_IRQ', 'PROJECT_OUTPUT_DIRECTORY output_files/IIe_Banking')
    qsf = once(qsf, top_source.as_posix(), top_path.as_posix())
    for name, data in [('MacLC_IIe_Banking.qsf', qsf),
                       ('MacLC_IIe_Banking.qpf', 'QUARTUS_VERSION = "17.0"\nPROJECT_REVISION = "MacLC_IIe_Banking"\n')]:
        target, saved = MACLC / name, WORK / name
        if target.exists():
            assert saved.exists() and target.read_bytes() == saved.read_bytes(), 'independently changed project: ' + name
        target.write_text(data, encoding='utf-8')
        saved.write_bytes(target.read_bytes())
    inputs = [Path(__file__), generator, ROOT / 'fixtures/experiments/card-irq-system/prepare.py', qip,
              BASE / 'files.qip', source_qsf, binding_source, top_source, *closure]
    result = {'project': str(MACLC / 'MacLC_IIe_Banking.qpf'), 'boundary': '2040 before softswitch tests',
              'full_quartus_build_run': False,
              'inputs_sha256': {str(p): sha(p) for p in inputs},
              'generated_sha256': {str(p): sha(p) for p in [*generated, binding_path, top_path, WORK / 'card_platform.qip',
                  WORK / 'files.qip', MACLC / 'MacLC_IIe_Banking.qsf', MACLC / 'MacLC_IIe_Banking.qpf']}}
    (HERE / 'project-results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS separate MacLC_IIe_Banking project generated', flush=True)
    return closure


if __name__ == '__main__':
    prepare()
