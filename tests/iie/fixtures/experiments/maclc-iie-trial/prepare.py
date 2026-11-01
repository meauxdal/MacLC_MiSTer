#!/usr/bin/env python3
"""Assemble a separate LC/card diagnostic trial with visible status."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MACLC = ROOT.parent / 'MacLC_MiSTer'
WORK = ROOT / 'local/experiments/maclc-iie-trial'
BASE = ROOT / 'local/experiments/maclc-iie-banking-build'
FINAL = ROOT / 'local/experiments/card-diagnostic-final'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'fixtures/experiments/card-diagnostic-final/results.json'
    pins = json.loads(manifest_path.read_text())['inputs_sha256']
    qip = BASE / 'card_platform.qip'
    closure = [Path(name) for name in re.findall(r'SYSTEMVERILOG_FILE "([^"]+)"', qip.read_text())]
    closure = [FINAL / p.name if (FINAL / p.name).is_file() else p for p in closure]
    closure.append(ROOT / 'fixtures/experiments/card-iwm/card_iwm_frontend.sv')
    for path in closure:
        assert sha(path) == pins[str(path)], str(path)
    copied = []
    for path in closure:
        target = WORK / path.name
        target.write_bytes(path.read_bytes())
        copied.append(target)
    card_path = WORK / 'card_irq_candidate.sv'
    card_source = once(card_path.read_text(), '(!capture_valid || !capture_write);',
                       '(cpu_running && !capture_valid);')
    card = once(card_source, '    output wire [15:0] cpu_address,',
                '    output wire [15:0] cpu_address,\n    output reg [15:0] instruction_address = 0,')
    card = once(card, '    wire [7:0] control;', '''    always @(posedge clk) begin
        if (!por_n) instruction_address <= 0;
        else if (cpu_ready && cpu_sync) instruction_address <= cpu_address;
    end
    wire [7:0] control;''')
    card_path.write_text(card, encoding='ascii')
    for name, marker in [('card_platform.sv', '.card_cpu_address(card_cpu_address),'),
                         ('card_pds_candidate.sv', '.cpu_address(card_cpu_address),')]:
        path = WORK / name
        text = once(path.read_text(), '    output wire [15:0] card_cpu_address,',
                    '    output wire [15:0] card_cpu_address,\n    output wire [15:0] instruction_address,')
        text = once(text, marker, marker + ' .instruction_address(instruction_address),')
        path.write_text(text, encoding='ascii')
    binding_source = BASE / 'maclc_iie_binding.sv'
    assert sha(binding_source) == pins[str(binding_source)]
    binding = once(binding_source.read_text(), '    output wire diagnostic_boundary, diagnostic_fault,',
                   '    output wire diagnostic_boundary, diagnostic_fault,\n    output wire [199:0] debug_status,')
    binding = once(binding, '    wire cold_ready', '''    wire [15:0] cpu_pc, cpu_bus, cap_address;
    wire cap_valid;
    wire [7:0] cap_status, cap_data;
    wire [31:0] cap_count, cpu_count;
    reg bus_active = 0;
    reg [31:0] bus_count = 0, bus_address = 0;
    reg [15:0] bus_data = 0;
    always @(posedge clk_sys) begin
        if (!reset_sys[1]) begin
            bus_active <= 0;
            bus_count <= 0;
            bus_address <= 0;
            bus_data <= 0;
        end else begin
            if (pds_as_n) bus_active <= 0;
            else if (claim && !dtack_n && !bus_active) begin
                bus_active <= 1;
                bus_count <= bus_count + 32'd1;
                bus_address <= pds_address;
                bus_data <= pds_rw ? pds_read_data : pds_write_data;
            end
        end
    end
    assign debug_status = {4'b0, claim, cap_valid, diagnostic_boundary, diagnostic_fault,
        cpu_pc, cap_address, cap_status, cap_data, cpu_bus, cap_count[15:0], cpu_count, bus_count, bus_address, bus_data};
    wire cold_ready''')
    binding = once(binding, '.card_cpu_address(), .capture_valid(), .capture_status(),',
                   '.card_cpu_address(cpu_bus), .instruction_address(cpu_pc), .capture_valid(cap_valid), .capture_status(cap_status),')
    binding = once(binding, '.capture_address(), .capture_data(), .capture_count(), .cpu_completed()',
                   '.capture_address(cap_address), .capture_data(cap_data), .capture_count(cap_count), .cpu_completed(cpu_count)')
    binding_path = WORK / 'maclc_iie_binding.sv'
    binding_path.write_text(binding, encoding='ascii')
    top_source = BASE / 'MacLC_IIe.sv'
    top = top_source.read_text(encoding='utf-8')
    top = once(top, '    wire iie_diagnostic_boundary, iie_diagnostic_fault;',
               '    wire iie_diagnostic_boundary, iie_diagnostic_fault;\n    wire [199:0] iie_debug_status;')
    top = once(top, '        .diagnostic_boundary(iie_diagnostic_boundary),',
               '        .debug_status(iie_debug_status), .diagnostic_boundary(iie_diagnostic_boundary),')
    start = top.index('`ifdef USE_DBG_HUD\n\t// Debug HUD')
    end = top.index('\n\tassign VGA_DE', start)
    top = top[:start] + '''    iie_status_overlay iie_status (
        .clk_sys(clk_sys), .clk_vid(clk_vid), .reset(!pll_locked),
        .ce_pixel(v8_ce_pix), .de(v8_de), .vblank(v8_vblank), .status_sys(iie_debug_status),
        .red_in(v8_vga_r), .green_in(v8_vga_g), .blue_in(v8_vga_b),
        .red_out(VGA_R), .green_out(VGA_G), .blue_out(VGA_B)
    );
''' + top[end:]
    top_path = WORK / 'MacLC_IIe.sv'
    top_path.write_text(top, encoding='utf-8')
    platform_qip = WORK / 'card_platform.qip'
    platform_qip.write_text(''.join('set_global_assignment -name SYSTEMVERILOG_FILE "' + p.as_posix() + '"\n' for p in copied), encoding='ascii')
    files = (BASE / 'files.qip').read_text()
    files = once(files, qip.as_posix(), platform_qip.as_posix())
    files = once(files, binding_source.as_posix(), binding_path.as_posix())
    files = once(files, top_source.as_posix(), top_path.as_posix())
    files += '\nset_global_assignment -name SYSTEMVERILOG_FILE "' + (HERE / 'iie_status_overlay.sv').as_posix() + '"\n'
    files_path = WORK / 'files.qip'
    files_path.write_text(files, encoding='utf-8')
    qsf_source = BASE / 'MacLC_IIe_Banking.qsf'
    qsf = once(qsf_source.read_text(encoding='utf-8'), (BASE / 'files.qip').as_posix(), files_path.as_posix())
    qsf = once(qsf, 'output_files/IIe_Banking', 'output_files/IIe_Trial')
    qsf = once(qsf, top_source.as_posix(), top_path.as_posix())
    for name, content in [('MacLC_IIe_Trial.qsf', qsf),
                          ('MacLC_IIe_Trial.qpf', 'QUARTUS_VERSION = "17.0"\nPROJECT_REVISION = "MacLC_IIe_Trial"\n')]:
        target = MACLC / name
        saved = WORK / name
        if target.exists():
            assert saved.exists() and target.read_bytes() == saved.read_bytes(), 'changed project: ' + str(target)
        target.write_text(content, encoding='utf-8')
        saved.write_bytes(target.read_bytes())
    inputs = [manifest_path, qip, binding_source, top_source, BASE / 'files.qip', qsf_source,
              HERE / 'prepare.py', HERE / 'iie_status_overlay.sv', *closure]
    record = {'project': str(MACLC / 'MacLC_IIe_Trial.qpf'),
              'scope': 'Full diagnostic candidate and IWM register frontend in LC; visible status; no ROM preloads or simulated host services in hardware',
              'boundary': '2055; pending captures and unsupported accesses remain guarded',
              'quartus_build_run': False,
              'inputs_sha256': {str(p): sha(p) for p in inputs},
              'generated_sha256': {str(p): sha(p) for p in [*copied, binding_path, top_path, platform_qip, files_path,
                  MACLC / 'MacLC_IIe_Trial.qsf', MACLC / 'MacLC_IIe_Trial.qpf']}}
    (HERE / 'project-results.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS MacLC_IIe_Trial project generated; baseline projects unchanged')
    return copied, binding_path


if __name__ == '__main__':
    prepare()
