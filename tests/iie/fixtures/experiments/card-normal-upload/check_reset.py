#!/usr/bin/env python3
"""Check the original reset path independently with an explicit firmware preload."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    spec = importlib.util.spec_from_file_location('prepare', HERE / 'prepare.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    prepare.WORK = ROOT / 'local/experiments/card-reset-prefix'
    original_prepare = prepare.prepare

    def build():
        sources, _, inputs = original_prepare()
        host = prepare.WORK / 'host.lua'
        source = prepare.once(host.read_text(),
            'space:write_u32(relocate(0x3efff4), live.main + 0x46a)',
            'space:write_u32(relocate(0x3efff4), live.main + 0x4300)')
        source = prepare.once(source, "cpu.state['A7'].value = relocate(0x3efff0)",
                              "cpu.state['A7'].value = relocate(0x3efff4)")
        host.write_text(source, encoding='ascii')
        image = ROOT / 'local/experiments/card-monitor-resume/initial.hex'
        return sources, image, inputs + [image, Path(__file__)]

    prepare.prepare = build
    sys.modules['prepare'] = prepare
    spec = importlib.util.spec_from_file_location('checks', prepare.CONTINUOUS / 'checks.py')
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    sys.modules['checks'] = checks
    source = (HERE / 'run.py').read_text()
    source = prepare.once(source, '\n    return source\n', '\n    return extend_reset(source)\n')

    def extend_reset(runner):
        runner = prepare.once(runner, "'protocol_requests': len(transactions) + 1", "'protocol_requests': len(transactions)")
        runner = prepare.once(runner, "'prelude_pds_requests': 6", "'prelude_pds_requests': 0")
        runner = prepare.once(runner, "'total_pds_requests': len(transactions) + (7 if args.poll_control == 'pause' else 15)",
                              "'total_pds_requests': len(transactions) + 9")
        runner = prepare.once(runner, "'original Monx loader writes/readback into empty native card RAM, live QuickDraw and driver initialization; supplied geometry and reset handshake'",
                              "'Original driver reset with explicit firmware preload; upload is not exercised'")
        runner = prepare.once(runner, 'destination = HERE / f\'', 'destination = HERE / f\'reset-smoke-')
        (prepare.WORK / 'runner.py').write_text(runner, encoding='ascii')
        return runner

    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('reset_smoke_runner', loader=None))
    module.extend_reset = extend_reset
    exec(compile(source, str(HERE / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
