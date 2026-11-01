#!/usr/bin/env python3
"""Check visible service-4 updates with glyph bank 1 retained after reload."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'card-reload-service4'
sys.path.insert(0, str(PARENT))


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def main():
    source = (PARENT / 'run.py').read_text()
    marker = "    source = (PARENT / 'run.py').read_text()"
    source = once(source, marker, marker + '''
    source = once(source, 'enumerate((0, 1, 0))', 'enumerate((0, 1, 1))')
    source = once(source, 'assert frames[0] == frames[2]', 'assert frames[1] == frames[2]')
    source = once(source, 'assert pcs.count(0x20040e) == 1', 'assert pcs.count(0x20040e) == 2')
''')
    source = once(source, 'callback.text.GLYPH_BANK = mode, 0',
                  'callback.text.GLYPH_BANK = mode, 128')
    marker = "    expected = callback.text.expected_frame(driver, main)"
    source = once(source, marker, marker + '''
    assert world[0x5960 - 0x970:0x5960 - 0x96e] == bytes.fromhex('8000')
    callback.text.GLYPH_BANK = 0
    assert expected != callback.text.expected_frame(driver, main), 'glyph banks indistinguishable'
    callback.text.GLYPH_BANK = 128
''')
    source = once(source, '    result.update(acks_forwarded=acks,',
                  '    result.update(settings_sequence=[0, 1, 1], retained_glyph_bank=128, acks_forwarded=acks,')
    source = once(source, "inputs += snapshots + sources + [HERE / 'run.py',",
                  "inputs += snapshots + sources + [ROOT / 'fixtures/experiments/card-reload-service4/run.py', HERE / 'run.py',")
    source = once(source, 'Original callback reload 0/1/0 followed by',
                  'Original callback reload 0/1/1 with glyph bank 1 retained, followed by')
    source = once(source, 'and two card RTIs; injected', 'and two card RTIs in positive cases; injected')
    source = once(source, "WORK = ROOT / 'local/experiments/card-reload-service4'",
                  "WORK = ROOT / 'local/experiments/card-reload-service4-bank'")
    module = type(sys)('retained_bank_runner')
    module.__file__ = str(HERE / 'run.py')
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
