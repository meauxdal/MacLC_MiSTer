#!/usr/bin/env python3
"""Check original BS3 mismatch dispatch and restored CPU status."""
import importlib.util
import os
import re
from prepare import HERE, PARENT, once

PROFILES = {'slot6': (0, 0xa5b6, 0xc6), 'slot8': (0, 0xa5b1, 0xc8),
            'override': (0xa5, 0xa5b1, 0xc6)}


def extend(source):
    source = once(source, "                fields = list(map(int, request.read_text().split()))", """                while True:
                    try:
                        fields = list(map(int, request.read_text().split()))
                        break
                    except (PermissionError, FileNotFoundError):
                        assert host.poll() is None and time.monotonic() < deadline, 'Bridge request unavailable'
                        time.sleep(0.002)""")
    source = source.replace('IIE_SKIP_BOOT_A=', 'IIE_WRONG_BOOT_P=')
    source = source.replace('host register return mismatch number=14', 'host register return mismatch number=16')
    source = source.replace('missing boot-A control escaped', 'wrong boot-P control escaped')
    source = source.replace("receive('PASS boot-service2')", "receive('PASS boot-service3')")
    source = source.replace('pcs.count(offset) == 3', 'pcs.count(offset) == 4')
    source = once(source, 'and pcs.count(0x1d84) == 1',
                  'and pcs.count(0x1d84) == 1 and pcs.count(0x1d8a) == 1')
    source = source.replace('in transactions) == 15', 'in transactions) == 20')
    source = source.replace('in transactions) == 18', 'in transactions) == 24')
    source = source.replace('len(transactions) == 156', 'len(transactions) == 206')
    source = source.replace('boot-a-fault', 'boot-p-fault').replace('00201d8400201d88', '00201db800201e0c')
    source = once(source,
        "            assert (run / 'boot-p-fault-before.bin').read_bytes() == (run / 'boot-p-fault-after.bin').read_bytes()",
        """            before = bytearray((run / 'boot-p-fault-before.bin').read_bytes())
            assert before[0x5960 - 0x891] & 2 == 0
            before[0x5960 - 0x891] |= 2
            assert (run / 'boot-p-fault-after.bin').read_bytes() == before""")
    source = source.replace('original boot service2 selection and CPU return; initialized flag/settings fixture',
                            'original first BS3 mismatch and CPU status return; initialized flag/settings fixture')
    source = once(source, "PARENT / 'run.py', *sources", "PARENT / 'run.py', HERE.parent / 'card-boot-service2/run.py', *sources")
    return source


def main():
    source = (PARENT / 'run.py').read_text()
    source = once(source, 'from prepare import HERE, PARENT, once',
                  "from prepare import HERE, once\nPARENT = HERE.parent / 'card-saved-register-live'")
    source = source.replace('len(saves) == 15 and len(records) == 33', 'len(saves) == 20 and len(records) == 44')
    source = source.replace('for service in range(3):', 'for service in range(4):')
    source = once(source, '            state[0] = boot_a', '            state[0] = boot_a\n        elif service == 3:\n            state[3] &= 0xfd')
    source = source.replace('(1, 4, 2)[service]', '(1, 4, 2, 3)[service]')
    source = once(source, "            assert (run / 'boot-preack-world.bin').read_bytes() == world",
                  "            assert (run / 'boot-preack-world.bin').read_bytes() == world\n"
                  "        elif service == 3:\n            assert (run / 'bs3-preack-world.bin').read_bytes() == world")
    source = source.replace("'service4-code.bin', 'boot-preack-code.bin', 'code-after.bin'",
                            "'service4-code.bin', 'boot-preack-code.bin', 'bs3-preack-code.bin', 'code-after.bin'")
    source = source.replace('services=3 returns=15 transactions=156', 'services=4 returns=20 transactions=206')
    source = once(source, "    spec = importlib.util.spec_from_file_location('boot_saved_runner'",
                  "    source = extend(source)\n    spec = importlib.util.spec_from_file_location('boot_saved_runner'")
    spec = importlib.util.spec_from_file_location('bs3_runner', PARENT / 'run.py')
    module = importlib.util.module_from_spec(spec)
    module.extend = extend
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    module.main()


if __name__ == '__main__':
    main()
