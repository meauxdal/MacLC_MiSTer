#!/usr/bin/env python3
"""Run original input-buffer handling and key echo over live PDS."""
import importlib.util
from prepare import KEY, WORK, once


def extend_echo(source):
    source = once(source, '    args = parser.parse_args()', '''    parser.add_argument('--echo-control', choices=('buffer', 'echo'))
    args = parser.parse_args()
    os.environ['IIE_ECHO_CONTROL'] = args.echo_control or ''
    assert not args.key_control
    assert not args.echo_control or (args.key == '41' and args.profile == 'slot6')''')
    source = once(source, "'+sys_phase=2'", "'+sys_phase=2', *(['+drop_' + args.echo_control] if args.echo_control else [])")
    source = once(source, "assert not args.prompt_control, 'prompt control escaped'", "assert not args.echo_control, 'echo control escaped'")
    source = once(source, "if not args.prompt_control or ('prompt store missing' if args.prompt_control == 'store' else 'idle seed carry missing') not in str(error):",
                  "if not args.echo_control or ('input buffer store missing' if args.echo_control == 'buffer' else 'key echo store missing') not in str(error):")
    source = once(source, '(1 if args.prompt_control else 0)', '(1 if args.echo_control else 0)')
    source = once(source, "'key_control': args.key_control,", "'key_control': args.key_control, 'echo_control': args.echo_control,")
    source = once(source, '"control" if args.key_control else "results"', '"control" if args.echo_control else "results"')
    source = once(source, "{'-' + args.key_control if args.key_control else ''}.json", "{'-' + args.echo_control if args.echo_control else ''}.json")
    source = once(source, "receive('PASS key-input')", "receive('PASS key-echo')")
    source = once(source, "'+key_instructions=' + linux(run / 'key-instructions.txt')",
                  "'+key_instructions=' + linux(run / 'key-instructions.txt'), '+echo_instructions=' + linux(run / 'echo-instructions.txt')")
    source = source.replace('original prompt, live PDS key arrival, original input tail and live service 6 return',
                            'original service 6 return, input-buffer handling and key echo; inherited prompt and host services')
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (KEY / 'run.py').read_text()
    source = once(source, '\n    return source\n', '\n    return extend_echo(source)\n')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('echo_runner', loader=None))
    module.extend_echo = extend_echo
    exec(compile(source, str(KEY / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
