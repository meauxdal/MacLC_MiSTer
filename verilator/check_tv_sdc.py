"""Execute the core SDC in Tcl 8.6 with strict Quartus-17 collection mocks.

Checks Tcl evaluation/exception topology, NOT real TimeQuest endpoint coverage.
Run with the bundled Windows Python (tkinter available); no Quartus invocation.
"""
from pathlib import Path
import re
import tkinter

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'crt_tv|stream|buffered.canvas|'
FIFO = PREFIX + 'capture_fifo|'
NATIVE = 'emu|pllv|pll_inst|divclk'
OTHER = 'sysmem|h2f_user0_clk'
TV = 'tv525_pll|pll_inst|divclk'


def check(profile, missing=False, missing_line=False):
    t = tkinter.Tcl()
    regs = ['emu|v8_video|rgb[0]', 'emu|v8_video|rd_gray_meta[0]']
    fanout = regs.copy()
    if profile != 'normal':
        regs += ['crt_tv|stream|osd|config_payload[0]',
                 'crt_tv|stream|osd|tv_config[0]', 'crt_tv|disable_meta']
    if profile == 'buffered':
        for name in ('wr_gray', 'rd_gray', 'wr_gray_meta', 'rd_gray_meta'):
            regs += [FIFO + name + f'[{bit}]' for bit in range(11)]
        fanout += [r for r in regs if r.startswith(FIFO + 'wr_gray[')
                   or r.startswith(FIFO + 'rd_gray_meta[')]
        regs += [PREFIX + 'line_payload[0]', PREFIX + 'store|bank',
                 PREFIX + 'store|address[0]', PREFIX + 'store|read_words[0]',
                 PREFIX + 'store|pair_meta']
    if missing:
        fanout = [r for r in fanout if 'rd_gray_meta[' not in r]
    if missing_line:
        regs = [r for r in regs if r != PREFIX + 'store|bank']
    clocks = [NATIVE, OTHER, TV]
    calls = []

    def items(value):
        return list(t.splitlist(value))

    def matches(pattern, value):
        return re.fullmatch(re.escape(pattern).replace(r'\*', '.*'), value) is not None

    def get_objects(objects, *args):
        args = list(args)
        if args and args[0] == '-nowarn':
            args.pop(0)
        assert len(args) <= 1, args
        patterns = items(args[0]) if args else ['*']
        return tuple(x for x in objects if any(matches(p, x) for p in patterns))

    t.createcommand('get_registers', lambda *a: get_objects(regs, *a))
    t.createcommand('get_keepers', lambda *a: get_objects(regs, *a))
    t.createcommand('get_clocks', lambda *a: get_objects(clocks, *a))
    t.createcommand('get_ports', lambda *a: get_objects(['VGA_R[0]'], *a))
    t.createcommand('get_pins', lambda *a: get_objects(['tv525_pll|pll_inst|locked'], *a))
    t.createcommand('get_collection_size', lambda a: len(items(a)))
    t.createcommand('remove_from_collection', lambda a, b: tuple(x for x in items(a) if x not in items(b)))
    t.createcommand('add_to_collection', lambda a, b: tuple(dict.fromkeys(items(a) + items(b))))

    def clock_info(option, clock):
        assert option == '-targets' and clock == NATIVE
        return ('native_pll_output',)

    def fanouts(option, targets):
        assert option == '-no_logic' and items(targets) == ['native_pll_output']
        return tuple(fanout)

    t.createcommand('get_clock_info', clock_info)
    t.createcommand('get_fanouts', fanouts)
    t.eval('proc foreach_in_collection {var collection body} {uplevel 1 [list foreach $var $collection $body]}')
    for command in ('derive_pll_clocks', 'derive_clock_uncertainty', 'set_false_path',
                    'set_clock_groups', 'set_max_delay', 'set_max_skew', 'set_multicycle_path', 'create_generated_clock', 'set_input_delay', 'set_output_delay'):
        t.createcommand(command, lambda *args, command=command: calls.append((command, args)) or '')
    # Deliberately no all_registers command: the original SDC must fail here.
    try:
        t.eval((ROOT / 'MacLC.sdc').read_text())
    except tkinter.TclError as e:
        if missing and str(e) == 'Native FIFO endpoints missing from video-clock fanout':
            print('PASS missing native endpoint fails closed')
            return
        if missing_line and str(e) == 'TV held-line mailbox endpoint missing; review synthesis hierarchy':
            print('PASS missing held-line endpoint fails closed')
            return
        raise
    assert not missing
    groups = [c for c in calls if c[0] == 'set_clock_groups']
    assert bool(groups) == (profile != 'buffered')
    if profile == 'buffered':
        for command, args in calls:
            if command == 'set_false_path' and '-hold' not in args:
                for option, excluded in (('-from', FIFO + 'wr_gray['),
                                         ('-to', FIFO + 'rd_gray_meta['),
                                         ('-to', FIFO + 'wr_gray_meta[')):
                    if option in args:
                        assert not any(x.startswith(excluded) for x in items(args[args.index(option) + 1]))
        delays = [a for c, a in calls if c == 'set_max_delay' and a[0] == '8.0']
        skews = [a for c, a in calls if c == 'set_max_skew' and a[0] == '8.0']
        assert len(delays) == len(skews) == 2
    print(f'PASS {profile}: SDC evaluated; exception topology checked')


for profile in ('normal', 'diagnostic', 'buffered'):
    check(profile)
check('buffered', missing=True)
check('buffered', missing_line=True)
