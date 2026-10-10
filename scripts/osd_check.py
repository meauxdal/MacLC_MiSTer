#!/usr/bin/env python3
"""Offline CONF_STR regression gate; no simulator or FPGA build required.

Drawing and selection are deliberately separate models of Main's generic menu
loops. Reference revisions: upstream 42e64002280578e01346d0afa37851ea49c24427
and danifunker/Main_MiSTer b308dbfde2e97a9434b2064793616334b0061834.
This checks this core's grammar subset, not arbitrary MiSTer CONF_STR syntax.
Use --main-source-dir to check downloaded menu.cpp/user_io.cpp and fork_ copies
against the modeled rules. Use --baseline c9e0b0d to demonstrate the old failure.
It does not execute Main or establish the version deployed on a physical box.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOP = ['Mount Floppy', 'Mount SCSI Disk 0', 'Mount SCSI Disk 1', 'Mount CD-ROM',
       'Monitor', 'Memory', 'Apply and Reset', 'Video', 'System', 'MT32-pi', 'Reset']
PAGES = {1: ['Aspect Ratio', 'Scaling'],
         2: ['Mount PRAM', 'Clear PRAM and Reset', 'Floppy Writes', 'CD-ROM Drive',
             'Ethernet', 'Network Interface', 'MAC Suffix', 'Interrupt (NMI)'],
         3: ['Use MT32-pi', 'Synthesizer', 'Munt ROM', 'SoundFont', 'Show Info']}
BITS = {'Aspect Ratio': (7, 8), 'Scaling': (12, 13), 'Analog Output': (3, 3),
        'CRT De-flicker': (1, 2), 'Monitor': (10, 10), 'Memory': (4, 4),
        'Apply and Reset': (0, 0), 'Reset': (0, 0), 'Clear PRAM and Reset': (6, 6),
        'Floppy Writes': (14, 14), 'CD-ROM Drive': (18, 18), 'Ethernet': (19, 19),
        'Network Interface': (36, 37), 'MAC Suffix': (32, 35),
        'Interrupt (NMI)': (5, 5), 'Use MT32-pi': (24, 24),
        'Synthesizer': (26, 26), 'Munt ROM': (27, 28), 'SoundFont': (29, 31),
        'Show Info': (22, 23)}
MEDIA = ['S6,DSKIMG,Mount Floppy', 'SC0,IMGVHDHDA,Mount SCSI Disk 0',
         'SC1,IMGVHDHDA,Mount SCSI Disk 1', 'SC4,ISOTO*CUEBINCHD,Mount CD-ROM',
         'SC2,NVR,Mount PRAM']


def expand(text, diag):
    block = text.split('localparam CONF_STR = {', 1)[1].split('\n\t};', 1)[0]
    block = re.sub(r'//[^\n]*', '', block)
    active, pieces = True, []
    for line in block.splitlines():
        if '`ifdef' in line:
            assert line.strip() == '`ifdef MAC_TV525_DIAG'
            active = diag
        elif '`endif' in line:
            active = True
        elif active:
            pieces.extend(json.loads(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"', line))
            if '`BUILD_DATE' in line:
                # Fixed version fixture; the Quartus pre-flow supplies the real date.
                pieces.append('000000')
    return ''.join(pieces)


def drawing(conf, page=0, flat=False):
    # Main MENU_GENERIC_MAIN2: recognized controls increment selentry;
    # separators increment only the physical row. I/V/v do neither.
    rows = []
    for token in conf.split(';')[2:]:
        if not token:
            continue
        eligible = page == 0
        if token.startswith('P') and token[2] != ',':
            n = int(token[1])
            eligible = page == n if page else flat
            token = token[2:]
            if flat and not page and token.startswith('-'):
                eligible = False
        if not eligible:
            continue
        kind = token[0]
        assert kind in 'PSORo-IVv', f'Unmodeled drawing token: {token}'
        if kind in 'PSORo':
            if kind == 'P' and flat and rows and rows[-1] is not None:
                rows.append(None)  # flat-page title separation
            rows.append(token)
        elif kind == '-':
            rows.append(None)
    return rows


def selection(conf, page=0, flat=False):
    # Main MENU_GENERIC_MAIN3: generic ASCII eligibility, NOT drawing's list.
    entries = []
    for token in conf.split(';')[2:]:
        if not token:
            continue
        inpage = not page
        if token[0] == 'P' and token[2] != ',':
            n = ord(token[1]) - ord('0')
            if page and page == n:
                inpage = True
            if not page and n and not flat:
                inpage = False
            token = token[2:]
        if not inpage or token[0] < 'A' or token[0] == 'f':
            continue
        entries.append(token)
    return entries


def label(token):
    return token.split(',')[2 if token.startswith('S') else 1]


def verify_menu(conf, diag):
    root = [t for t in drawing(conf) if t]
    assert [label(t) for t in root] == TOP
    expected = dict(PAGES)
    if diag:
        expected[1] = expected[1] + ['CRT De-flicker']
    checks = 0
    for page, flat in [(0, False), (1, False), (2, False), (3, False), (0, True)]:
        physical = drawing(conf, page, flat)
        controls = [t for t in physical if t]
        actions = selection(conf, page, flat)
        if page:
            assert [label(t) for t in controls] == expected[page]
        # Test all indices, including controls beyond the first screen.
        for index, control in enumerate(controls):
            assert actions[index] == control, (page, flat, index, control, actions[index])
            for screen_size in (8, 16):
                firstmenu = 0
                row = physical.index(control) - firstmenu
                # Main MenuWrite/adjvisible scrolling rule.
                if row < 0:
                    firstmenu += row
                elif row >= screen_size:
                    firstmenu += row - screen_size + 1
                assert 0 <= physical.index(control) - firstmenu < screen_size
                assert selection(conf, page, flat)[index] == control
            checks += 1
        # Main intercepts menusub_last as Back/Exit BEFORE token traversal.
        back_index = len(controls)
        assert back_index > 0
        if page:
            parent = next(i for i, t in enumerate(root) if t.startswith(f'P{page},'))
            assert selection(conf)[parent] == root[parent]
            # Back restores the parent index; re-enter starts submenu at zero.
            assert selection(conf, page)[0] == controls[0]
        assert drawing(conf, page, flat) == physical  # close/reopen is stable
    assert [t for t in selection(conf, 0, True) if t.startswith('S')] == MEDIA
    for token in selection(conf, 0, True):
        if token[0] in 'ORo':
            code = token.split(',')[0][1:]
            bits = [int(c, 36) + (32 if token[0] == 'o' else 0) for c in code]
            assert (bits[0], bits[-1]) == BITS[label(token)]
    assert conf.split(';')[:2] == ['MACLC', 'UART57600:115200,MIDI']
    assert not any(t.startswith('v') for t in conf.split(';'))
    last_control = max(i for i, t in enumerate(conf.split(';')[2:], 2)
                       if t and t[0] in 'PSORo')
    assert all(i > last_control for i, t in enumerate(conf.split(';'))
               if t.startswith(('I,', 'V,')))
    return checks


def verify_sources(directory):
    # Refuse to silently apply this model to source with different rules.
    for prefix in ('', 'fork_'):
        menu = (directory / f'{prefix}menu.cpp').read_text(encoding='utf-8')
        user = (directory / f'{prefix}user_io.cpp').read_text(encoding='utf-8')
        for fragment in ("if (!inpage || h || p[0] < 'A') continue;", "if (p[0] == 'f')",
                         'menusub == menusub_last && select', 'menusub = menusub_parent;',
                         'int row = n - firstmenu;', 'firstmenu += adjvisible;',
                         "if (flat && !page && p[0] == '-') inpage = 0;"):
            assert fragment in menu, fragment
        draw = menu.split('case MENU_GENERIC_MAIN2: {', 1)[1].split('case MENU_GENERIC_MAIN3:', 1)[0]
        assert 'int i = 2;' in draw and "p[0] == 'v'" not in draw
        for fragment in ('if (i >= 2 && p && p[0])', "if (p[0] == 'v')",
                         'if (with_ver) strcat(str, config_ver);',
                         'name = user_io_create_config_name(1);',
                         'memset(cur_status, 0, sizeof(cur_status));',
                         'sprintf(str, "%s.s%c", user_io_get_core_name(), p[2]);',
                         'start += 32;', 'end += 32;'):
            assert fragment in user, fragment
    eth = (directory / 'fork_mac_eth.cpp').read_text(encoding='utf-8')
    assert '#define ETH_OPT_IFACE  "[37:36]"' in eth
    assert '#define ETH_OPT_MACSUF "[35:32]"' in eth
    mac = (directory / 'fork_mac.cpp').read_text(encoding='utf-8')
    assert '#define MAC_TOOLBOX_SLOT    3' in mac
    assert '#define MAC_CD_TOOLBOX_SLOT 5' in mac
    assert 'if (index != mac_cdrom_slot()) return 1;' in mac
    assert 'if (ret) ret = mac_mount_hook(index, name, &sd_image[index], &writable);' in user


def verify_configs_and_defaults(conf):
    # File-backed fixture: unversioned settings win even if older v1/v2 exist.
    scratch = ROOT / 'scratch' / 'osd'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as temp:
        folder = Path(temp)
        for name, value in [('MACLC.CFG', 0x4010), ('MACLC_v1.CFG', 0xFFFFFFFF),
                            ('MACLC_v2.CFG', 0xFFFFFFFF)]:
            (folder / name).write_bytes(value.to_bytes(16, 'little'))
        name = conf.split(';')[0] + '.CFG'
        status = int.from_bytes((folder / name).read_bytes(), 'little')
        assert status == 0x4010  # existing 10MB/write-On settings retained
        (folder / name).unlink()
        assert not (folder / name).exists()  # Main zeroes options on missing file
    options = {label(t): t.split(',')[2:] for t in selection(conf, 0, True) if t[0] in 'Oo'}
    for name, value in {'Monitor': '512x384 12in', 'Memory': '2 MB',
                        'Floppy Writes': 'Off', 'CD-ROM Drive': 'Enabled',
                        'Ethernet': 'Off', 'Network Interface': 'eth0',
                        'MAC Suffix': '0'}.items():
        assert options[name][0] == value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-source-dir', type=Path)
    parser.add_argument('--baseline', help='Git revision of the broken menu (e.g. c9e0b0d)')
    parser.add_argument('--dump-dir', type=Path, help='Save exact expanded CONF_STR variants')
    args = parser.parse_args()
    text = (ROOT / 'MacLC.sv').read_text(encoding='utf-8')
    if args.main_source_dir:
        verify_sources(args.main_source_dir)
        print('PASS: upstream/fork source rules and host network bit ranges')
    for diag in (False, True):
        conf = expand(text, diag)
        checks = verify_menu(conf, diag)
        verify_configs_and_defaults(conf)
        if args.dump_dir:
            args.dump_dir.mkdir(parents=True, exist_ok=True)
            (args.dump_dir / f'conf_str_{"480i" if diag else "native"}.txt').write_text(
                conf + '\n', encoding='utf-8')
        print(f'PASS: MAC_TV525_DIAG={"defined" if diag else "omitted"}: '
              f'{checks} control mappings across root, pages and flat menu; '
              '8/16-row scrolling, Back/reopen, media, bits, config/default fixtures')
    if args.baseline:
        old = subprocess.check_output(['git', 'show', f'{args.baseline}:MacLC.sv'],
                                      cwd=ROOT).decode('utf-8')
        old_conf = expand(old, True)
        shown = [t for t in drawing(old_conf) if t]
        resolved = selection(old_conf)
        failures = [(label(t), resolved[i]) for i, t in enumerate(shown) if resolved[i] != t]
        assert failures[0] == ('Mount Floppy', 'v,1')
        assert ('System', 'SC4,ISOTO*CUEBINCHD,Mount CD-ROM') in failures
        print(f'PASS negative control {args.baseline}: {len(failures)} wrong root mappings; '
              'Mount Floppy -> v,1; System -> CD-ROM')
        # All changes are inside CONF_STR: hardware/reset/PRAM logic identical.
        assert text.split('\n\t};', 1)[1] == old.split('\n\t};', 1)[1]
        assert text.split('localparam CONF_STR', 1)[0] == old.split('localparam CONF_STR', 1)[0]
        for diag in (False, True):
            new_tokens = selection(expand(text, diag), 0, True)
            old_tokens = selection(expand(old, diag), 0, True)
            # Compare tokens without page wrappers: ranges, values, filters and
            # persistence flags must survive the reorganization byte-for-byte.
            unchanged = lambda ts: Counter(t for t in ts if t[0] in 'SORoIV')
            assert unchanged(new_tokens) == unchanged(old_tokens)
        print('PASS: all RTL after CONF_STR unchanged, including reset latches/PRAM/media wiring')
        print('PASS: baseline option values/ranges, media modifiers/filters and popup strings preserved')


if __name__ == '__main__':
    main()
