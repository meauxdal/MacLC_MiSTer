#!/usr/bin/env python3
"""Run original firmware upload before live card startup and rendering."""
import importlib.util
from prepare import CONTINUOUS, WORK, once


def extend_upload(source):
    source = once(source, "str(HERE / 'bootstrap.lua')", "str(CONTINUOUS / 'bootstrap.lua')")
    source = once(source, "'protocol_requests': len(transactions)", "'protocol_requests': len(transactions) + 1")
    source = once(source, "from prepare import HERE, ROOT, WORK, prepare, sha", "from prepare import HERE, ROOT, WORK, CONTINUOUS, prepare, sha")
    source = once(source, "'real QuickDraw glyph construction and original driver initialization followed by live polling; firmware preload and supplied host geometry'",
                  "'original Monx loader writes/readback into empty native card RAM, live QuickDraw and driver initialization; supplied geometry and reset handshake'")
    (WORK / 'runner.py').write_text(source, encoding='ascii')
    return source


def main():
    source = (CONTINUOUS / 'run.py').read_text()
    source = once(source, '\n    return source\n', '\n    return extend_upload(source)\n')
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('upload_runner', loader=None))
    module.extend_upload = extend_upload
    exec(compile(source, str(CONTINUOUS / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
