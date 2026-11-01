#!/usr/bin/env python3
"""Run the bounded original polling/display experiment."""
import importlib.util
from prepare import RENDER, WORK, once


def extend_poll(source):
    source = once(source, '    args = parser.parse_args()', '''    parser.add_argument('--poll-control', choices=('status', 'pause'))
    args = parser.parse_args()
    os.environ['IIE_POLL_CONTROL'] = args.poll_control or ''
    assert args.profile == 'slot6' and args.key == '41' and not args.render_control''')
    source = once(source, "receive('PASS prompt-render')", "receive('PASS poll-display')")
    start = source.index("        delivery = re.findall(")
    end = source.index("        result = {", start)
    source = source[:start] + "        key_delivery = None\n" + source[end:]
    source = once(source, "        assert len(delivery) == 1 and delivery[0] == (args.key, '1', '281')", '') if '        assert len(delivery)' in source else source
    source = once(source, "'total_pds_requests': len(transactions) + 17", "'total_pds_requests': len(transactions) + 16")
    source = once(source, "'protocol_requests': len(transactions) + 1", "'protocol_requests': len(transactions)")
    source = once(source, "if not args.echo_control or ('input buffer store missing' if args.echo_control == 'buffer' else 'key echo store missing') not in str(error):",
                  "if args.poll_control != 'pause' or 'runtime hold blocked pending response' not in str(error):")
    source = once(source, 'assert rtl.wait(timeout=10) == (1 if args.echo_control else 0)',
                  "assert rtl.wait(timeout=10) == int(args.poll_control == 'pause')")
    source = once(source, "        if args.render_control:\n            assert rejection == 'prompt pixel or framebuffer guard mismatch'", "        if args.poll_control:\n            assert rejection == ('runtime hold blocked pending response' if args.poll_control == 'pause' else 'live prompt pixel mismatch')")
    source = once(source, "'render_control': args.render_control,", "'render_control': args.render_control, 'poll_control': args.poll_control,")
    source = once(source, '"control" if args.render_control else "results"', '"control" if args.poll_control else "results"')
    source = once(source, "{'-' + args.render_control if args.render_control else ''}.json", "{'-' + args.poll_control if args.poll_control else ''}.json")
    source = once(source, "'prelude_pds_requests': 16", "'prelude_pds_requests': 6, 'pause_probe_requests': 9")
    source = once(source, "'total_pds_requests': len(transactions) + 16", "'total_pds_requests': len(transactions) + (7 if args.poll_control == 'pause' else 15)")
    source = source.replace('original input/echo followed by scheduled original text refresh and rendering from live card RAM',
                            'original polling and read-triggered display selection; initializer and glyph snapshots')
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (RENDER / 'run.py').read_text()
    source = once(source, '\n    return source\n', '\n    return extend_poll(source)\n')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('poll_runner', loader=None))
    module.extend_poll = extend_poll
    exec(compile(source, str(RENDER / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
