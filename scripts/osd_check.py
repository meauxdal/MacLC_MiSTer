#!/usr/bin/env python3
"""Offline CONF_STR regression gate; no simulator or FPGA build required.

Drawing and selection are deliberately separate models of Main's generic menu
loops. Reference revisions: upstream 42e64002280578e01346d0afa37851ea49c24427
and danifunker/Main_MiSTer b308dbfde2e97a9434b2064793616334b0061834.
This checks this core's grammar subset, not arbitrary MiSTer CONF_STR syntax.
Use --main-source-dir to check downloaded menu.cpp/user_io.cpp and fork_ copies
against the modeled rules. --baseline checks saved values against upstream.
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
TOP = ['Pri. disk (ID 0)', 'Disk (ID 1)', 'Floppy disk', 'Load ROM',
       'Memory', 'Machine', 'Video', 'Advanced', 'Apply and reset']
PAGES = {1: ['IIe ROM mapping', 'Interrupt (NMI)', 'Clear PRAM and reset'],
         2: ['Monitor', 'Aspect ratio', 'Scale', 'IIe trial overlay'],
         5: ['PRAM image', 'Floppy writes']}
BITS = {'Aspect ratio': (7, 8), 'Scale': (12, 13),
        'Monitor': (10, 10), 'Memory': (4, 4),
        'Apply and reset': (0, 0), 'Clear PRAM and reset': (6, 6),
        'Floppy writes': (14, 14), 'Interrupt (NMI)': (5, 5),
        'IIe ROM mapping': (18, 18), 'IIe trial overlay': (9, 9),
        'Deflicker': (1, 2)}
MEDIA = ['SC0,IMGVHDHDA,Pri. disk (ID 0)', 'SC1,IMGVHDHDA,Disk (ID 1)',
         'S6,DSKIMG,Floppy disk', 'F0,ROM,Load ROM', 'SC2,NVR,PRAM image']


def expand(text, diag):
    block = text.split('localparam CONF_STR = {', 1)[1].split('\n\t};', 1)[0]
    block = re.sub(r'//[^\n]*', '', block)
    active, pieces = True, []
    for line in block.splitlines():
        if '`ifdef' in line:
            assert line.strip() == '`ifdef MAC_TV525'
            active = diag
        elif '`endif' in line:
            active = True
        elif active:
            pieces.extend(json.loads(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"', line))
            if '`BUILD_DATE' in line:
                # Fixed version fixture; the Quartus pre-flow supplies the real date.
                pieces.append('000000')
    return ''.join(pieces)


def drawing(conf, page=0, flat=False, hdmask=0):
    # Main MENU_GENERIC_MAIN2: recognized controls increment selentry;
    # separators increment only the physical row. I/V/v do neither.
    rows = []
    for token in conf.split(';')[2:]:
        if not token:
            continue
        hidden = False
        while token[0] in 'Hh':
            flag = bool(hdmask & (1 << int(token[1], 36)))
            hidden |= flag if token[0] == 'H' else not flag
            token = token[2:]
        eligible = page == 0
        if token.startswith('P') and token[2] != ',':
            n = int(token[1])
            eligible = page == n if page else flat
            token = token[2:]
            if flat and not page and token.startswith('-'):
                eligible = False
        if hidden or not eligible:
            continue
        kind = token[0]
        assert kind in 'PFSORo-IVv', f'Unmodeled drawing token: {token}'
        if kind in 'PFSORo':
            if kind == 'P' and flat and rows and rows[-1] is not None:
                rows.append(None)  # flat-page title separation
            rows.append(token)
        elif kind == '-':
            rows.append(None)
    return rows


def selection(conf, page=0, flat=False, hdmask=0):
    # Main MENU_GENERIC_MAIN3: generic ASCII eligibility, NOT drawing's list.
    entries = []
    for token in conf.split(';')[2:]:
        if not token:
            continue
        hidden = False
        while token[0] in 'Hh':
            flag = bool(hdmask & (1 << int(token[1], 36)))
            hidden |= flag if token[0] == 'H' else not flag
            token = token[2:]
        inpage = not page
        if token[0] == 'P' and token[2] != ',':
            n = ord(token[1]) - ord('0')
            if page and page == n:
                inpage = True
            if not page and n and not flat:
                inpage = False
            token = token[2:]
        if hidden or not inpage or token[0] < 'A' or token[0] == 'f':
            continue
        entries.append(token)
    return entries


def label(token):
    return token.split(',')[2 if token[0] in 'SF' else 1]


def all_controls(conf):
    return list(dict.fromkeys(t for mask in range(16)
                             for t in selection(conf, 0, True, mask)))


def verify_menu(conf, diag, hdmask):
    root = [t for t in drawing(conf) if t]
    assert [label(t) for t in root] == TOP
    expected = dict(PAGES)
    if diag:
        expected[2] = ['Monitor', 'Deflicker', *PAGES[2][1:]]
    checks = 0
    for page, flat in [(0, False), *[(page, False) for page in PAGES], (0, True)]:
        physical = drawing(conf, page, flat, hdmask)
        controls = [t for t in physical if t]
        actions = selection(conf, page, flat, hdmask)
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
                assert selection(conf, page, flat, hdmask)[index] == control
            checks += 1
        # Main intercepts menusub_last as Back/Exit BEFORE token traversal.
        back_index = len(controls)
        assert back_index > 0
        if page:
            parent = next(i for i, t in enumerate(root) if t.startswith(f'P{page},'))
            assert selection(conf)[parent] == root[parent]
            # Back restores the parent index; re-enter starts submenu at zero.
            assert selection(conf, page, hdmask=hdmask)[0] == controls[0]
        assert drawing(conf, page, flat, hdmask) == physical  # close/reopen is stable
    assert [t for t in selection(conf, 0, True, hdmask) if t[0] in 'SF'] == MEDIA
    for token in all_controls(conf):
        if token[0] in 'ORo':
            code = token.split(',')[0][1:]
            bits = [int(c, 36) + (32 if token[0] == 'o' else 0) for c in code]
            assert (bits[0], bits[-1]) == BITS[label(token)]
    assert conf.split(';')[:2] == ['MACLC', 'UART57600:115200,MIDI']
    assert not any(t.startswith('v') for t in conf.split(';'))
    last_control = max(i for i, t in enumerate(conf.split(';')[2:], 2)
                       if t and (t[0] in 'PFSORo' or t.startswith(('H', 'h'))))
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
    options = {label(t): t.split(',')[2:] for t in all_controls(conf) if t[0] in 'Oo'}
    for name, value in {'Monitor': '640x480 VGA', 'Memory': '2MB',
                        'Floppy writes': 'Off', 'IIe ROM mapping': 'Automatic',
                        'IIe trial overlay': 'On'}.items():
        assert options[name][0] == value


def verify_pending(text, conf, diag):
    # Only machine configuration requires Apply and reset.
    expected = set()
    for token in all_controls(conf):
        if token[0] == 'O' and label(token) in ('Memory', 'Monitor'):
            code = token.split(',')[0][1:]
            expected.update(range(int(code[0], 36), int(code[-1], 36) + 1))
    block = text.split('localparam [31:0] CFG_MASK =', 1)[1].split(';', 1)[0]
    values = [int(value, 16) for value in re.findall(r"32'h([0-9A-F]+)", block)]
    mask = values[0]
    assert mask == sum(1 << bit for bit in expected)
    assert len(drawing(conf, hdmask=1)) == len(drawing(conf, hdmask=0)) + 1
    # The upstream monitor encoding must also match the ROM's sense IDs.
    assert "v8_monitor_id = cfg[10] ? 4'h2 : 4'h6;" in text
    assert 'configRAMSize = cfg[4]' in text
    assert 'wire [1:0] ar = status[8:7];' in text
    assert '.SCALE(status[13:12])' in text
    assert 'assign flp_int_wp = ~status[14] || flp_int_ro;' in text
    assert set(re.findall(r'\bcfg\[([^]]+)\]', text)) == {'4', '10'}
    assert '.enable_sys(!status[9])' in text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-source-dir', type=Path)
    parser.add_argument('--baseline', help='Git revision to check saved option values against')
    parser.add_argument('--dump-dir', type=Path, help='Save exact expanded CONF_STR variants')
    args = parser.parse_args()
    text = (ROOT / 'MacLC.sv').read_text(encoding='utf-8')
    if args.main_source_dir:
        verify_sources(args.main_source_dir)
        print('PASS: upstream/fork source rules and host network bit ranges')
    for diag in (False, True):
        conf = expand(text, diag)
        checks = sum(verify_menu(conf, diag, mask) for mask in range(16))
        verify_configs_and_defaults(conf)
        verify_pending(text, conf, diag)
        if args.dump_dir:
            args.dump_dir.mkdir(parents=True, exist_ok=True)
            (args.dump_dir / f'conf_str_{"480i" if diag else "native"}.txt').write_text(
                conf + '\n', encoding='utf-8')
        print(f'PASS: MAC_TV525={"defined" if diag else "omitted"}: '
              f'{checks} control mappings across root, pages and flat menu; '
              'hide masks, 8/16-row scrolling, Back/reopen, media, pending bits, config/default fixtures')
    if args.baseline:
        old = subprocess.check_output(['git', 'show', f'{args.baseline}:MacLC.sv'],
                                      cwd=ROOT).decode('utf-8')
        for diag in (False, True):
            new_tokens = all_controls(expand(text, diag))
            old_tokens = all_controls(expand(old, diag))
            # Labels may change; stored option values and media indices may not.
            def saved_values(tokens):
                return Counter((t.split(',')[0], tuple(v.replace(' ', '') for v in t.split(',')[2:]))
                               for t in tokens if t[0] in 'Oo')
            additions = [t for t in new_tokens
                         if label(t) in ('IIe ROM mapping', 'IIe trial overlay', 'Deflicker')]
            assert not (saved_values(new_tokens) - saved_values(old_tokens) - saved_values(additions))
            old_by_label = {label(t): t for t in old_tokens}
            for token in new_tokens:
                if label(token) in old_by_label:
                    assert token == old_by_label[label(token)], (token, old_by_label[label(token)])
            media = lambda ts: Counter(tuple(t.split(',')[:2]) for t in ts if t[0] == 'S')
            assert not (media(new_tokens) - media(old_tokens))
        print(f'PASS: {args.baseline} remaining saved option values and media slots/filters preserved')


if __name__ == '__main__':
    main()
