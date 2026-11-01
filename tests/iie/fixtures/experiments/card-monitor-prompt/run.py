#!/usr/bin/env python3
"""Run the original Applesoft prompt continuation with live host services."""
import importlib.util
from prepare import HERE, POST, WORK, once


def extend_prompt(source):
    source = once(source, "receive('PASS post-match')", "receive('PASS prompt')")
    source = once(source, '    args = parser.parse_args()', '''    parser.add_argument('--prompt-control', choices=('store', 'seed'))
    parser.set_defaults(finish_init=True)
    args = parser.parse_args()
    os.environ['IIE_PROMPT_CONTROL'] = args.prompt_control or ''
    assert not (args.control or args.routing_control or args.switch_control)''')
    source = once(source, "*(['+wrong_e000'] if args.routing_control else [])",
                  "*(['+drop_prompt' if args.prompt_control == 'store' else '+drop_seed'] if args.prompt_control else [])")
    source = once(source, "assert not args.routing_control, 'wrong E000 routing control escaped'",
                  "assert not args.prompt_control, 'prompt control escaped'")
    source = once(source, "if not args.routing_control or 'cold E000 routing mismatch' not in str(error):",
        "if not args.prompt_control or ('prompt store missing' if args.prompt_control == 'store' else 'idle seed carry missing') not in str(error):")
    source = once(source, 'assert rtl.wait(timeout=10) == (1 if args.routing_control else 0)',
                  'assert rtl.wait(timeout=10) == (1 if args.prompt_control else 0)')
    source = once(source, "'driver': driver, 'routing_control':", "'driver': driver, 'prompt_control': args.prompt_control, 'routing_control':")
    source = once(source, '"control" if args.control or args.routing_control or args.switch_control else "results"',
                  '"control" if args.prompt_control else "results"')
    source = once(source, "{'-switch' if args.switch_control else ''}.json", "{'-' + args.prompt_control if args.prompt_control else ''}.json")
    source = source.replace('original matching BS3 and Applesoft cold-start RAM sizing; modeled resource traps and initializer snapshots',
                            'original Applesoft prompt and 260 idle keyboard polls; inherited cold start and live host services')
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (POST / 'run.py').read_text()
    source = once(source, '        return source', '        return extend_prompt(source)')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('prompt_runner', loader=None))
    module.extend_prompt = extend_prompt
    exec(compile(source, str(POST / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
