#!/usr/bin/env python3
"""Generate a separate local MacLC diagnostic project; never edit sys or baseline RTL."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MACLC = Path('C:/Workspace/Git/MacLC_MiSTer')
WORK = ROOT / 'local/experiments/maclc-iie-build'
DORMANT = HERE.parent / 'maclc-card-integration'
PINS = {
    'MacLC.sv': '3bafa309638a9325cbff5401b06402d066b9e8ac2340aafacf14549617a7e1f0',
    'files.qip': '2dfeea36a23f868d079b2361ffc2507f654bd584a530839b8a4155f6234d303d',
    'rtl/sdram.v': '953c6a255646ced9ce01cc5b0367bfe496e6fc24aa747d3135fc36d9315f2d04',
    'rtl/floppy_sd.v': '511ab0548c7f4f2d712bdc737b6442b006264ecaca75f01a5383ce3fa0424988',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(source, before, after):
    assert source.count(before) == 1, before
    return source.replace(before, after)


def prepare():
    for name, pin in PINS.items():
        assert digest(MACLC / name) == pin, name
    WORK.mkdir(parents=True, exist_ok=True)
    # Reuse reviewed, baseline-pinned seam and allocation transforms.
    for script in (DORMANT / 'prepare.py', HERE.parent / 'card-memory-allocation/prepare_loader.py'):
        subprocess.run([sys.executable, '-B', str(script)], check=True, timeout=15, cwd=ROOT)
    source = (ROOT / 'local/experiments/maclc-card-integration/MacLC.sv').read_text(encoding='utf-8')
    source = re.sub(r'^`ifdef APPLE_IIE_CARD_DORMANT_SEAMS\n(.*?)^`endif\n',
                    lambda match: match.group(1).split('`else\n')[0], source, flags=re.M | re.S)
    assert 'APPLE_IIE_CARD_DORMANT_SEAMS' not in source
    source = once(source, '// Dormant seams only. No card instance or live activation is provided.',
                  '// Experimental diagnostic card; backend survives warm Mac reset.')
    for old, new in [("wire iie_card_claim_raw = 1'b0;", 'wire iie_card_claim_raw;'),
                     ("wire iie_card_dtack_n = 1'b1;", 'wire iie_card_dtack_n;'),
                     ("wire iie_card_error = 1'b0;", 'wire iie_card_error;'),
                     ("wire [15:0] iie_card_read_data = 16'hFFFF;", 'wire [15:0] iie_card_read_data;'),
                     (" || (iie_card_claim && iie_card_error);", ';')]:
        source = once(source, old, new)
    source = once(source, '// Native pass-through until a reviewed card_platform binding exists.',
                  '// Card and floppy share the native port through locked ownership.')
    source = once(source, 'wire iie_native_req = flp_mem_req;', 'wire iie_native_req;')
    source = once(source, "wire iie_native_we = 1'b0;", 'wire iie_native_we;')
    source = once(source, 'wire [23:0] iie_native_addr = flp_mem_addr;', 'wire [23:0] iie_native_addr;')
    source = once(source, "wire [15:0] iie_native_din = 16'b0;", 'wire [15:0] iie_native_din;')
    source = once(source, '\tassign flp_mem_ack = iie_native_ack;\n\tassign flp_mem_dout = iie_native_dout;', '')
    instance = '''
    wire iie_memory_ready;
    maclc_iie_binding iie_card (
        .clk_sys(clk_sys), .clk_mem(clk_mem), .pll_locked(pll_locked),
        .memory_ready(iie_memory_ready), .host_reset(!_cpuReset),
        .pds_address(cpuAddr), .pds_fc(cpuFC), .pds_as_n(_cpuAS),
        .pds_uds_n(_cpuUDS), .pds_lds_n(_cpuLDS), .pds_rw(_cpuRW), .pds_write_data(cpuDataOut),
        .claim(iie_card_claim_raw), .dtack_n(iie_card_dtack_n), .error(iie_card_error),
        .pds_read_data(iie_card_read_data),
        .floppy_req(flp_mem_req), .floppy_addr(flp_mem_addr), .floppy_ack(flp_mem_ack), .floppy_data(flp_mem_dout),
        .native_req(iie_native_req), .native_we(iie_native_we), .native_addr(iie_native_addr),
        .native_din(iie_native_din), .native_ack(iie_native_ack), .native_dout(iie_native_dout)
    );
'''
    source = once(source, '\tsdram sdram\n', instance + '\tsdram sdram\n')
    # User-approved first-build policy: only PLL loss starts SDRAM init.
    start = source.index('\t// Dedicated SDRAM re-init pulse')
    end = source.index('    wire iie_memory_ready;', start)
    source = source[:start] + '\t// Diagnostic build: SDRAM init only on cold PLL loss.\n\n' + source[end:]
    start = source.index('\t\t// Full init at config')
    end = source.index('\t\t.clk_64', start)
    source = source[:start] + '\t\t.init           ( !pll_locked ),\n\t\t.memory_ready   ( iie_memory_ready ),\n' + source[end:]
    assert 'sdram_reinit' not in source
    (WORK / 'MacLC_IIe.sv').write_text(source, encoding='utf-8')
    controller = (MACLC / 'rtl/sdram.v').read_text(encoding='utf-8')
    controller = once(controller, '\tinput               init,', '\toutput              memory_ready,\n\tinput               init,')
    controller = once(controller, "initial reset = 10'h3FF;", "assign memory_ready = reset == 0 && !init;\ninitial reset = 10'h3FF;")
    (WORK / 'sdram.v').write_text(controller, encoding='utf-8')
    replacements = {'MacLC.sv': WORK / 'MacLC_IIe.sv', 'rtl/sdram.v': WORK / 'sdram.v',
                    'rtl/floppy_sd.v': ROOT / 'local/experiments/card-memory-allocation/floppy_sd_bounded.v'}
    files = (MACLC / 'files.qip').read_text()
    for old, new in replacements.items():
        files = once(files, ' ' + old + '\n', ' "' + new.as_posix() + '"\n')
    files += '\nset_global_assignment -name QIP_FILE "' + (WORK / 'card_platform.qip').as_posix() + '"\n'
    files += 'set_global_assignment -name SYSTEMVERILOG_FILE "' + (HERE / 'maclc_iie_binding.sv').as_posix() + '"\n'
    (WORK / 'files.qip').write_text(files, encoding='utf-8')
    qsf = (MACLC / 'MacLC.qsf').read_text()
    qsf = once(qsf, 'source files.qip', 'source "' + (WORK / 'files.qip').as_posix() + '"')
    qsf = once(qsf, 'PROJECT_OUTPUT_DIRECTORY output_files', 'PROJECT_OUTPUT_DIRECTORY output_files/IIe')
    for old, new in replacements.items():
        # QSF repeats part of files.qip; keep duplicate assignments identical.
        qsf = once(qsf, ' ' + old + '\n', ' "' + new.as_posix() + '"\n') if ' ' + old + '\n' in qsf else qsf
    for name, data in [('MacLC_IIe.qsf', qsf), ('MacLC_IIe.qpf', 'QUARTUS_VERSION = "17.0"\nPROJECT_REVISION = "MacLC_IIe"\n')]:
        target = MACLC / name
        if target.exists():
            saved = WORK / name
            assert saved.is_file() and saved.read_bytes() == target.read_bytes(), 'unowned project file: ' + str(target)
        target.write_text(data, encoding='utf-8')
        (WORK / name).write_bytes(target.read_bytes())
    qip = HERE.parent / 'card-platform/card_platform.qip'
    closure = [(qip.parent / name).resolve() for name in re.findall(r'\[file join \$::quartus\(qip_path\) ([^\]]+)\]', qip.read_text())]
    assert len(closure) == 12 and all(path.is_file() for path in closure), 'missing card QIP dependency'
    # Quartus 17 ignores ASYNC_REG; retain the same logic with native metadata.
    crossing = HERE.parent / 'card-memory-cdc/card_memory_cdc.sv'
    cdc = crossing.read_text().replace('(* ASYNC_REG = "TRUE" *)',
        '(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \\"FORCED IF ASYNCHRONOUS\\"" *)')
    (WORK / 'card_memory_cdc.sv').write_text(cdc, encoding='ascii')
    closure = [WORK / 'card_memory_cdc.sv' if p == crossing.resolve() else p for p in closure]
    (WORK / 'card_platform.qip').write_text(''.join(
        'set_global_assignment -name SYSTEMVERILOG_FILE "' + p.as_posix() + '"\n' for p in closure), encoding='ascii')
    for name, pin in PINS.items():
        assert digest(MACLC / name) == pin, name
    inputs = [*closure, crossing, qip, HERE / 'maclc_iie_binding.sv', Path(__file__),
              *(MACLC / name for name in PINS), MACLC / 'MacLC.qsf', MACLC / 'MacLC.sdc',
              DORMANT / 'prepare.py', HERE.parent / 'card-memory-allocation/prepare_loader.py']
    result = {'project': str(MACLC / 'MacLC_IIe.qpf'), 'baseline_sources_unchanged': True,
              'reset_policy': 'cold PLL init only; backend survives warm host resets; power cycle for full restart',
              'card_boundary': '202F diagnostic prefix', 'reserved_word_range': '540000-55FFFF',
              'quartus_build_run': False,
              'inputs_sha256': {str(path): digest(path) for path in inputs},
              'generated_sha256': {str(path): digest(path) for path in [*WORK.glob('*.sv'), WORK / 'sdram.v', WORK / 'files.qip', WORK / 'card_platform.qip', MACLC / 'MacLC_IIe.qsf', MACLC / 'MacLC_IIe.qpf']}}
    (HERE / 'project-results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print('PASS separate MacLC_IIe project generated; twelve card sources present; baseline unchanged')
    return closure


if __name__ == '__main__':
    prepare()
