#!/usr/bin/env python3
"""Check original boot-service selection and live CPU return."""
import importlib.util
import os
import re
from prepare import HERE, PARENT, once

PROFILES = {'slot6': (0, 0xa5b6, 0xc6), 'slot8': (0, 0xa5b1, 0xc8),
            'override': (0xa5, 0xa5b1, 0xc6)}


def check_host(driver, run, snapshots, records, output, render):
    flag, config, boot_a = PROFILES[os.environ['IIE_BOOT_PROFILE']]
    original = (render.CODE / f'CODE_{driver}.bin').read_bytes()
    transformed = bytes(value | 0x80 for value in original[0x1e14:0x1ebc])
    assert (run / 'frame.bin').read_bytes() == render.expected_frame(driver, transformed)
    assert (run / 'boot-profile.bin').read_bytes() == bytes([flag]) + config.to_bytes(2, 'big')
    world = bytearray(snapshots['card-display-init', driver, 'world.bin'].read_bytes())
    world[0x5960 - 0x5814] = flag
    world[0x5960 - 0x86c:0x5960 - 0x86a] = config.to_bytes(2, 'big')
    world[0x5960 - 0x1236:0x5960 - 0x1232] = (0xe00000).to_bytes(4, 'big')
    world[0x5960 - 0x97c:0x5960 - 0x97a] = bytes(2)
    world[0x5960 - 0x4372:0x5960 - 0x4372 + len(transformed) * 2] = \
        bytes(value for item in transformed for value in (1, item))
    for _, _, address in render.visible_cells():
        if 0x650 <= address < 0x6f8:
            world[0x5960 - 0x4812 + (address - 0x400) * 2] = 0
    saves = [(int(index), int(value, 16)) for index, value in re.findall(
        r'^SAVE register=(\d) value=([0-9a-f]+)$', '\n'.join(output), re.M)]
    assert len(saves) == 15 and len(records) == 33
    state = list(snapshots['card-display-init', driver, 'world.bin'].read_bytes()[
        0x5960 - 0x894:0x5960 - 0x88f])
    position = 0
    for service in range(3):
        for index, value in saves[service * 5:service * 5 + 5]:
            state[index] = value
            assert records[position][2:4] == [12, 0] and records[position][4:] == state
            position += 1
        if service == 1:
            state[2] = 9
        elif service == 2:
            state[0] = boot_a
        assert records[position][2:4] == [12, 0] and records[position][4:] == state
        position += 1
        world[0x5960 - 0x894:0x5960 - 0x88f] = bytes(state)
        world[0x5960 - 0x88f] = (1, 4, 2)[service]
        if service == 1:
            assert (run / 'service4-world.bin').read_bytes() == world
        elif service == 2:
            assert (run / 'boot-preack-world.bin').read_bytes() == world
        for index in (4, 3, 2, 1, 0):
            assert records[position][2:4] == [25, state[index]] and records[position][4:] == state
            position += 1
    assert (run / 'world.bin').read_bytes() == world, 'final full boot world mismatch'
    code = bytearray(snapshots['card-display-init', driver, 'code-after.bin'].read_bytes())
    code[0x1e14:0x1ebc] = transformed
    for name in ('service4-code.bin', 'boot-preack-code.bin', 'code-after.bin'):
        assert (run / name).read_bytes() == code
    assert (run / 'loaded.bin').read_bytes() == original
    assert (run / 'state.txt').read_text().strip() == \
        'services=3 returns=15 transactions=156 pc=20281c sp=3f0000'


def main():
    source = (PARENT / 'run.py').read_text()
    source = once(source, "    args = parser.parse_args()", """    parser.add_argument('--profile', choices=('slot6', 'slot8', 'override'), default='slot6')
    args = parser.parse_args()
    os.environ['IIE_BOOT_PROFILE'] = args.profile""")
    source = once(source, "'+sys_phase=2'", "'+sys_phase=2', '+boot_a=' + str(PROFILES[args.profile][2])")
    source = once(source, 'IIE_SKIP_SAVED_Y=str(int(args.control))',
                  'IIE_SKIP_BOOT_A=str(int(args.control)), IIE_BOOT_PROFILE=args.profile')
    source = source.replace('host register return mismatch number=7', 'host register return mismatch number=14')
    source = source.replace('missing saved-Y control escaped', 'missing boot-A control escaped')
    source = source.replace("receive('PASS saved-register')", "receive('PASS boot-service2')")
    source = source.replace('pcs.count(offset) == 2', 'pcs.count(offset) == 3')
    source = once(source, '            assert pcs.count(0x1ee0) == 1',
                  '            assert pcs.count(0x1ee0) == 1 and pcs.count(0x1d66) == 1 and pcs.count(0x1d84) == 1')
    source = source.replace('in transactions) == 10', 'in transactions) == 15')
    source = source.replace('in transactions) == 12', 'in transactions) == 18')
    source = source.replace('len(transactions) == 106', 'len(transactions) == 156')
    source = source.replace('saved-y-fault', 'boot-a-fault').replace('00201ee000201ee6', '00201d8400201d88')
    source = source.replace("'driver': driver, 'control':", "'driver': driver, 'profile': args.profile, 'control':")
    source = source.replace('original CODE saved-register exchange through live PDS and paced CPU; initializer snapshots',
                            'original boot service2 selection and CPU return; initialized flag/settings fixture')
    source = once(source, "HERE / 'run.py', *sources", "HERE / 'run.py', PARENT / 'run.py', *sources")
    source = once(source, '-{driver}.json', '-{driver}-{args.profile}.json')
    spec = importlib.util.spec_from_file_location('boot_saved_runner', PARENT / 'run.py')
    module = importlib.util.module_from_spec(spec)
    module.PARENT, module.PROFILES = PARENT, PROFILES
    exec(compile(source, str(PARENT / 'run.py'), 'exec'), module.__dict__)
    module.check_host = check_host
    module.main()


if __name__ == '__main__':
    main()
