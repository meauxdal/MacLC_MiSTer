#!/usr/bin/env python3
"""Run original key consumption and service 6 against live PDS."""
import importlib.util
from prepare import PROMPT, WORK, once


def extend_key(source):
    source = once(source, '    args = parser.parse_args()', '''    parser.add_argument('--key', choices=('41', '15', '7f'), default='41')
    parser.add_argument('--key-control', choices=('strobe', 'clear'))
    args = parser.parse_args()
    os.environ['IIE_KEY'] = args.key
    os.environ['IIE_KEY_CONTROL'] = args.key_control or ''
    assert args.prompt_control is None''')
    source = once(source, "'+sys_phase=2'", "'+sys_phase=2', '+key=' + str(int(args.key, 16)), '+key_instructions=' + linux(run / 'key-instructions.txt')")
    source = once(source, "*(['+drop_prompt' if args.prompt_control == 'store' else '+drop_seed'] if args.prompt_control else [])",
                  "*(['+missing_strobe' if args.key_control == 'strobe' else '+missing_clear'] if args.key_control else [])")
    source = once(source, "if args.control and 'host register return mismatch number=21' in str(error):",
                  "if args.key_control and ('key strobe creation missing' if args.key_control == 'strobe' else 'key clear completion missing') in str(error):")
    source = once(source, '            if not args.control:\n                assert host.wait',
                  '            if not args.control and not args.key_control:\n                assert host.wait')
    source = once(source, "                assert rejected is not None, 'missing matching-P control escaped'", """                assert rejected is not None, 'key control escaped'
                if host.poll() is None:
                    host.terminate()
                    host.wait(timeout=5)""")
    source = once(source, "receive('PASS prompt')", "receive('PASS key-input')")
    source = once(source, "'driver': driver, 'prompt_control':", "'driver': driver, 'key': args.key, 'key_control': args.key_control, 'prompt_control':")
    source = once(source, "        result = {'scope':", """        delivery = re.findall(r'^KEY_DELIVERY raw=([0-9a-f]+) offset=18 width=8 pulses=(\\d+) total_pds=(\\d+)$', '\\n'.join(output), re.M)
        assert len(delivery) == 1 and delivery[0] == (args.key, '1', '281')
        key_delivery = {'write': True, 'width': 8, 'offset': 24, 'value': int(args.key, 16),
                        'keyboard_write_pulses': 1, 'pds_requests_after_delivery': 281}
        result = {'key_delivery': key_delivery, 'prelude_pds_requests': 16,
            'total_pds_requests': 281 if args.key_control else 331, 'scope':""")
    source = once(source, '"control" if args.prompt_control else "results"', '"control" if args.key_control else "results"')
    source = once(source, "{'-' + args.prompt_control if args.prompt_control else ''}.json",
                  "-key{args.key}{'-' + args.key_control if args.key_control else ''}.json")
    source = source.replace('original Applesoft prompt and 260 idle keyboard polls; inherited cold start and live host services',
                            'original prompt, live PDS key arrival, original input tail and live service 6 return')
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (PROMPT / 'run.py').read_text()
    source = once(source, '\n    return source\n', '\n    return extend_key(source)\n')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('key_runner', loader=None))
    module.extend_key = extend_key
    exec(compile(source, str(PROMPT / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
