#!/usr/bin/env python3
"""Check normal vector selection, service restoration and testbench lint."""
import json
import shlex
import subprocess
from prepare import HERE, ROOT, WORK, once, prepare, sha
from run import linux, wsl


def main():
    closure, inputs = prepare()
    pins_path = HERE / 'results-1.json'
    pins = json.loads(pins_path.read_text())['inputs_sha256']
    bench = WORK / 'tb_monitor.sv'
    image = WORK / 'initial.hex'
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    controller = ROOT / 'local/experiments/maclc-iie-build/sdram.v'
    sources = [bench, binding, *closure, controller]
    for path in (*sources, image):
        assert sha(path) == pins[str(path)], 'changed monitor source: ' + str(path)
    lint_bench = WORK / 'tb_monitor_lint.sv'
    lint_bench.write_text(once(bench.read_text(), '    defparam dut.platform.card.card.PACE_FAST = FAST;\n', ''),
                          encoding='ascii')
    _, lint = wsl(['verilator', '--lint-only', '--timing', '-Wno-fatal', '-DTB_NO_TRISTATE',
                   '--top-module', 'tb_card_platform', linux(lint_bench), *map(linux, sources[1:])])
    warnings = [line for line in lint.splitlines() if line.startswith('%Warning')]
    assert len(warnings) == 2 and all('sdram.v:' in line and 'WIDTHEXPAND' in line for line in warnings), lint
    card = WORK / 'card_irq_candidate.sv'
    text = card.read_text()
    controls = []
    for name, broken_text, expected in (
        ('common_vectors', once(text, "? 18'h27FFA +", "? 18'h23FFA +"), 'normal NMI vector mismatch'),
        ('bad_register_read', once(text, 'cpu_rdata = service_regs[cpu_address[2:0]];',
             "cpu_rdata = service_regs[cpu_address[2:0]] ^ (cpu_address == 16'hC078 ? 8'h01 : 8'h00);"),
             'monitor service did not restore interrupted execution'),
    ):
        broken = WORK / f'{name}.sv'
        broken.write_text(broken_text, encoding='ascii')
        binary = WORK / f'{name}.vvp'
        variant = [broken if path == card else path for path in sources]
        wsl(['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
             '-Ptb_card_platform.FAST=1', '-o', linux(binary), *map(linux, variant)])
        result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join([
            'vvp', linux(binary), '+image=' + linux(image), '+trace=' + linux(WORK / f'{name}-captures.txt'),
            '+instructions=' + linux(WORK / f'{name}-instructions.txt')])],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and expected in result.stdout and not result.stderr, result.stdout + result.stderr
        print('PASS rejected ' + name, flush=True)
        controls.append({'control': name, 'result': result.stdout.strip()})
        inputs.append(broken)
    inputs += [pins_path, HERE / 'check_controls.py', lint_bench, image, *sources]
    (HERE / 'control-results.json').write_text(json.dumps({
        'controls': controls, 'lint': 'default-rate full bench: two existing SDRAM width warnings only',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
