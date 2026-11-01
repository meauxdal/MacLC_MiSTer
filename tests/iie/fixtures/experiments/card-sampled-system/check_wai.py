#!/usr/bin/env python3
"""Exercise WAI through actual card commands, arbiter and delayed memory replies."""
import json
import shlex
import subprocess
from prepare import HERE, WORK, prepare, sha, once
from run import linux, wsl


def main():
    closure, _, inputs = prepare()
    bench = HERE / 'tb_wai.sv'
    sources = [bench, *closure]
    runs = []
    for fast in (0, 1):
        for masked in (0, 1):
            binary = WORK / f'wai-{fast}-{masked}.vvp'
            wsl(['iverilog', '-g2012', '-s', 'tb_wai', f'-Ptb_wai.FAST={fast}',
                 f'-Ptb_wai.MASKED={masked}', '-o', linux(binary), *map(linux, sources)])
            output, errors = wsl(['vvp', linux(binary)])
            assert 'PASS WAI' in output and not errors, output + errors
            print(output, flush=True)
            runs.append({'fast': fast, 'masked': masked, 'result': output})
    processor = WORK / 'card_irq_cpu_bus.sv'
    broken = WORK / 'no_wai_ready.sv'
    broken.write_text(once(processor.read_text(), '.rdy(waiting || ready)', '.rdy(ready)'), encoding='ascii')
    binary = WORK / 'no_wai_ready.vvp'
    wsl(['iverilog', '-g2012', '-s', 'tb_wai', '-o', linux(binary),
         *[linux(broken if path == processor else path) for path in sources]])
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(['vvp', linux(binary)])],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'WAI timeout' in result.stdout and not result.stderr, result.stdout + result.stderr
    print('PASS missing WAI RDY allowance rejected', flush=True)
    inputs += [HERE / 'prepare.py', HERE / 'run.py', HERE / 'check_wai.py', *sources]
    (HERE / 'wai-results.json').write_text(json.dumps({
        'scope': 'actual card host commands and arbiter; synthetic delayed word memory',
        'runs': runs, 'negative_control': result.stdout.strip(),
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
