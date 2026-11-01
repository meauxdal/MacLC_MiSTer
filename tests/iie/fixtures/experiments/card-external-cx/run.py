#!/usr/bin/env python3
"""Check external Cx routing and natural admission to the matching BS3 page."""
import importlib.util
from prepare import BASE, HERE, WORK, once


def main():
    spec = importlib.util.spec_from_file_location('external_cx_runner', BASE / 'run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inherited = module.extend

    def extend(source):
        source = inherited(source)
        source = once(source, '    render = load_render()', """    assert not args.control, 'Use --routing-control for the external routing control'
    assert args.profile in ('slot6', 'override'), 'This fixture stops at the second BS3 request'
    os.environ['IIE_CX_CONTROL'] = str(int(args.routing_control))
    render = load_render()""")
        source = once(source, '    args = parser.parse_args()',
                      "    parser.add_argument('--routing-control', action='store_true')\n    args = parser.parse_args()")
        source = once(source, "str(HERE / 'host.lua')", "str(WORK / 'host.lua')")
        source = once(source, "                receive('PASS boot-service3')\n                assert rtl.wait(timeout=10) == 0", """                if args.routing_control:
                    try:
                        receive('PASS external-cx')
                    except AssertionError as error:
                        assert 'external Cx routing mismatch address=c505 physical=20505 data=38' in str(error), str(error)
                        rejected = str(error)
                    assert rejected is not None, 'internal-ROM routing control escaped'
                    assert rtl.wait(timeout=10) != 0
                else:
                    receive('PASS external-cx')
                    assert rtl.wait(timeout=10) == 0""")
        source = source.replace('original first BS3 mismatch and CPU status return; initialized flag/settings fixture',
            'external C505 read after live BS3 mismatch; initial fill fixture; stop at matching C4 request')
        source = once(source, "'profile': args.profile,", "'profile': args.profile, 'routing_control': args.routing_control,")
        source = once(source, '        inputs += snapshot_inputs', """        if not args.routing_control:
            scan = (run / 'instructions.txt').read_text().splitlines()[-8:]
            assert [line.split()[:2] for line in scan] == [
                ['fac2', 'f0'], ['fac4', '8d'], ['fac7', 'b1'], ['fac9', 'd9'],
                ['facc', 'd0'], ['faba', 'a0'], ['fabc', 'c6'], ['fabe', 'a5']]
            assert scan[3].split()[2] == 'A=ea'
        command = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME',
            '-Wno-PINCONNECTEMPTY', '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps',
            '--top-module', 'maclc_iie_binding', *map(linux, sources[1:])]
        lint = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)],
                              capture_output=True, text=True, timeout=30)
        assert lint.returncode == 0 and not lint.stderr, lint.stdout + lint.stderr
        inputs += snapshot_inputs""")
        source = once(source, '"control" if args.control else "results"',
                      '"control" if args.routing_control else "results"')
        source = once(source, "HERE / 'run.py', PARENT / 'run.py',",
                      "HERE / 'run.py', HERE.parent / 'card-boot-service3/run.py', PARENT / 'run.py',")
        return source

    module.extend = extend
    module.main()


if __name__ == '__main__':
    main()
