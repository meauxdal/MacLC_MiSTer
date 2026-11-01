#!/usr/bin/env python3
"""Run original matching BS3 through Applesoft cold-start RAM sizing."""
import importlib.util
from prepare import BASE, HERE, WORK, once


def main():
    spec = importlib.util.spec_from_file_location('matching_runner', BASE / 'run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inherited = module.extend

    def extend(source):
        source = inherited(source)
        source = once(source, "    args = parser.parse_args()", """    parser.add_argument('--routing-control', action='store_true')
    parser.add_argument('--finish-init', action='store_true')
    parser.add_argument('--switch-control', action='store_true')
    args = parser.parse_args()
    assert sum((args.control, args.routing_control, args.switch_control)) <= 1
    assert not args.switch_control or args.finish_init
    os.environ['IIE_WRONG_E000'] = str(int(args.routing_control))
    os.environ['IIE_FINISH_INIT'] = str(int(args.finish_init))
    os.environ['IIE_WRONG_SWITCH'] = str(int(args.switch_control))""")
        source = once(source, "'+sys_phase=2'", "'+sys_phase=2', *(['+wrong_e000'] if args.routing_control else [])")
        source = once(source, '    render = load_render()',
            "    assert args.profile in ('slot6', 'override'), 'Matching resource fixture requires C4 selection'\n"
            '    render = load_render()')
        source = once(source, 'IIE_WRONG_BOOT_P=str(int(args.control))',
            "IIE_MATCH_RESOURCE=(WORK / 'str5101.bin').as_posix(), IIE_SKIP_MATCH_P=str(int(args.control))")
        source = once(source, "str(HERE / 'host.lua')", "str(WORK / 'host.lua')")
        source = source.replace('host register return mismatch number=16', 'host register return mismatch number=21')
        source = source.replace('wrong boot-P control escaped', 'missing matching-P control escaped')
        source = once(source, "                receive('PASS boot-service3')\n                assert rtl.wait(timeout=10) == 0", """                try:
                    receive('PASS post-match')
                    assert not args.routing_control, 'wrong E000 routing control escaped'
                except AssertionError as error:
                    if not args.routing_control or 'cold E000 routing mismatch' not in str(error):
                        raise
                    rejected = str(error)
                assert rtl.wait(timeout=10) == (1 if args.routing_control else 0)""")
        start = source.index("                rtl.stdin.write('-1 0 0 0 0\\n')")
        end = source.index('\n            else:\n                assert rejected', start)
        block = source[start:end]
        source = source[:start] + """                if args.switch_control:
                    rejected = 'wrong display status reaches original slot handler before ACK'
                else:
""" + '\n'.join('    ' + line for line in block.splitlines()) + source[end:]
        start = source.index('        if not args.control:\n            pcs =')
        end = source.index('        inputs += snapshot_inputs', start)
        source = source[:start] + """        from checks import check_host as check_matching
        check_matching(driver, run, snapshots, records, output, render, args.control, transactions)
        command = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME',
            '-Wno-PINCONNECTEMPTY', '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps',
            '--top-module', 'maclc_iie_binding', *map(linux, sources[1:])]
        lint = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)],
                              capture_output=True, text=True, timeout=30)
        assert lint.returncode == 0 and not lint.stderr, lint.stdout + lint.stderr
""" + source[end:]
        source = source.replace('original first BS3 mismatch and CPU status return; initialized flag/settings fixture',
            'original matching BS3 and Applesoft cold-start RAM sizing; modeled resource traps and initializer snapshots')
        source = once(source, "'driver': driver, 'profile':", "'driver': driver, 'routing_control': args.routing_control, 'switch_control': args.switch_control, 'finish_init': args.finish_init, 'profile':")
        source = once(source, '-{driver}-{args.profile}.json', "-{driver}-{args.profile}{'-init' if args.finish_init else ''}{'-routing' if args.routing_control else ''}{'-switch' if args.switch_control else ''}.json")
        source = once(source, '"control" if args.control else "results"',
                      '"control" if args.control or args.routing_control or args.switch_control else "results"')
        source = once(source, "HERE / 'run.py', PARENT / 'run.py',",
            "HERE / 'run.py', HERE.parent / 'card-boot-service3/run.py', PARENT / 'run.py',")
        source = once(source, "        result = {'scope':", """        from shutil import copyfile
        inputs.append(WORK / 'runner.py')
        saved_inputs = run / 'inputs'
        saved_inputs.mkdir()
        pinned_inputs = []
        for path in dict.fromkeys(inputs):
            if path.is_relative_to(WORK) and not path.is_relative_to(run):
                saved = saved_inputs / path.relative_to(WORK)
                saved.parent.mkdir(parents=True, exist_ok=True)
                copyfile(path, saved)
                pinned_inputs.append(saved)
            else:
                pinned_inputs.append(path)
        inputs = pinned_inputs
        result = {'scope':""")
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / 'runner.py').write_text(source, encoding='ascii')
        return source

    module.extend = extend
    module.main()


if __name__ == '__main__':
    main()
