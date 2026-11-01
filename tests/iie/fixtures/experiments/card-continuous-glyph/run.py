#!/usr/bin/env python3
"""Run live QuickDraw initialization followed by original display polling."""
import importlib.util
from prepare import HERE, POLL, WORK, once


def extend_continuous(source):
    source = once(source, "    assert args.profile == 'slot6' and args.key == '41' and not args.render_control",
                  "    assert args.profile == 'slot6' and args.key == '41' and not args.render_control and not args.poll_control")
    source = once(source, "IIE_RENDER_GLYPH=(WORK / 'glyph.bin').as_posix(),", "IIE_LIVE_HOST=(WORK / 'host.lua').as_posix(), IIE_DRIVER=str(driver),")
    source = once(source, "'-rompath', str(ROM.parent.parent), '-ramsize'",
                  "'-rompath', str(ROM.parent.parent), '-hard', str(WORK / 'autostart.chd'), '-ramsize'")
    source = once(source, "'-seconds_to_run', '51'", "'-seconds_to_run', '85'")
    source = once(source, "str(WORK / 'host.lua')", "str(HERE / 'bootstrap.lua')")
    source = once(source, "'original polling and read-triggered display selection; initializer and glyph snapshots'",
                  "'real QuickDraw glyph construction and original driver initialization followed by live polling; firmware preload and supplied host geometry'")
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (POLL / 'run.py').read_text()
    source = once(source, '\n    return source\n', '\n    return extend_continuous(source)\n')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('continuous_runner', loader=None))
    module.extend_continuous = extend_continuous
    exec(compile(source, str(POLL / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
