#!/usr/bin/env python3
"""Check mapping provenance, sticky fault reporting and status panel pixels."""
import json
from pathlib import Path

from prepare_runtime import ROOT, RTL, WORK, runtime_sources, sha
from check_runtime import linux, run


def main():
    sources = runtime_sources()
    mapping = ROOT / 'tools/tb_runtime_mapping.sv'
    overlay = ROOT / 'tools/tb_status_overlay.sv'
    binary = WORK / 'hardware-trace-mapping.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_runtime_mapping', '-o', linux(binary),
         linux(mapping), *map(linux, sources)])
    mapping_result = run(['vvp', linux(binary)])
    binary = WORK / 'hardware-trace-overlay.vvp'
    panel = RTL / 'iie_status_overlay.sv'
    run(['iverilog', '-g2012', '-s', 'tb_status_overlay', '-o', linux(binary),
         linux(overlay), linux(panel)])
    preview = WORK / 'hardware-trace-overlay.ppm'
    overlay_result = run(['vvp', linux(binary), '+output=' + linux(preview)])
    binding = RTL / 'maclc_iie_binding.sv'
    run(['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
         '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module',
         'maclc_iie_binding', linux(binding), *map(linux, sources)])
    run(['verilator', '--lint-only', '-Wall', '--top-module', 'iie_status_overlay', linux(panel)])
    record = {'mapping': mapping_result, 'overlay': overlay_result, 'lint': 'pass',
              'scope': 'Simulation of sampled start context, sticky first fault and panel; not a hardware diagnosis',
              'sha256': {str(p): sha(p) for p in [*sources, mapping, overlay, panel, binding, Path(__file__)]}}
    (WORK / 'hardware-trace-checks.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
    print('PASS hardware trace checks')


if __name__ == '__main__':
    main()
