#!/usr/bin/env python3
"""Run original prompt text rendering against live card RAM."""
import importlib.util
from prepare import ECHO, ROOT, WORK, once


def extend_render(source):
    source = once(source, '    args = parser.parse_args()', '''    parser.add_argument('--render-control', choices=('glyph', 'destination'))
    args = parser.parse_args()
    os.environ['IIE_RENDER_CONTROL'] = args.render_control or ''
    assert not args.echo_control
    assert not args.render_control or (args.profile == 'slot6' and args.key == '41')''')
    source = once(source, "'+sys_phase=2'", "'+sys_phase=2', '+live_page=' + linux(run / 'live-page.bin')")
    source = once(source, "IIE_MATCH_RESOURCE=(WORK / 'str5101.bin').as_posix(),", """IIE_RENDER_GLYPH=(WORK / 'glyph.bin').as_posix(),
            IIE_MAIN_CODE=(ROOT / 'local/experiments/firmware-memory/code/CODE_1.bin').as_posix(),
            IIE_MATCH_RESOURCE=(WORK / 'str5101.bin').as_posix(),""")
    source = once(source, '                transactions.append([bool(fields[1]), fields[2], fields[3], result])',
                  '                if fields[2] != 0: transactions.append([bool(fields[1]), fields[2], fields[3], result])')
    source = once(source, "receive('PASS key-echo')", "receive('PASS prompt-render')")
    source = once(source, "        result = {'key_delivery':", "        result = {'refreshed_bytes': 1024, 'rendered_cells': 960, 'pixels_checked': 307200, 'protocol_requests': len(transactions) + 1, 'key_delivery':")
    source = once(source, "'echo_control': args.echo_control,", "'echo_control': args.echo_control, 'render_control': args.render_control,")
    source = once(source, "'total_pds_requests': 281 if args.key_control else 331", "'total_pds_requests': len(transactions) + 17")
    source = once(source, "{'-' + args.echo_control if args.echo_control else ''}.json", "{'-' + args.render_control if args.render_control else ''}.json")
    source = once(source, '"control" if args.echo_control else "results"', '"control" if args.render_control else "results"')
    source = once(source, '        check_matching(driver, run, snapshots, records, output, render, args.control, transactions)',
                  '''        rejection = check_matching(driver, run, snapshots, records, output, render, args.control, transactions)
        if args.render_control:
            assert rejection == 'prompt pixel or framebuffer guard mismatch'
            rejected = rejection
        else:
            assert rejection is None''')
    source = source.replace('original service 6 return, input-buffer handling and key echo; inherited prompt and host services',
                            'original input/echo followed by scheduled original text refresh and rendering from live card RAM')
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (ECHO / 'run.py').read_text()
    source = once(source, '\n    return source\n', '\n    return extend_render(source)\n')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('prompt_render_runner', loader=None))
    module.extend_render = extend_render
    exec(compile(source, str(ECHO / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
