#!/usr/bin/env python3
"""Run original matching BS3 through live PDS and the monitor's BEQ."""
import importlib.util
from prepare import BASE, HERE, WORK, once


def main():
    spec = importlib.util.spec_from_file_location('matching_runner', BASE / 'run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inherited = module.extend

    def extend(source):
        source = inherited(source)
        source = once(source, '    render = load_render()',
            "    assert args.profile in ('slot6', 'override'), 'Matching resource fixture requires C4 selection'\n"
            '    render = load_render()')
        source = once(source, 'IIE_WRONG_BOOT_P=str(int(args.control))',
            "IIE_MATCH_RESOURCE=(WORK / 'str5101.bin').as_posix(), IIE_SKIP_MATCH_P=str(int(args.control))")
        source = once(source, "str(HERE / 'host.lua')", "str(WORK / 'host.lua')")
        source = source.replace('host register return mismatch number=16', 'host register return mismatch number=21')
        source = source.replace('wrong boot-P control escaped', 'missing matching-P control escaped')
        source = once(source, "receive('PASS boot-service3')", "receive('PASS matching-bs3')")
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
            'original matching BS3 admitted by live external scan; modeled resource traps; returned Z and BEQ')
        source = once(source, "HERE / 'run.py', PARENT / 'run.py',",
            "HERE / 'run.py', HERE.parent / 'card-boot-service3/run.py', PARENT / 'run.py',")
        return source

    module.extend = extend
    module.main()


if __name__ == '__main__':
    main()
