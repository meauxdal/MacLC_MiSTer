"""Evaluate core timing constraints with collection mocks, including negative cases."""
from pathlib import Path
import re
import tkinter

ROOT=Path(__file__).resolve().parents[1]
NATIVE='emu|pllv|pll_inst|divclk'
MEMORY='emu|pll|pll_inst|mem|divclk'
SDRAM='emu|pll|pll_inst|sys|divclk'
TV='emu|tv525_pll|pll_inst|divclk'
HDMI='pll_hdmi|pll_hdmi_inst|altera_pll_i|divclk'
FIFO='emu|crt_tv|canvas|capture_fifo|'
STORE='emu|crt_tv|canvas|store|'

def check(enabled,missing=None):
    t=tkinter.Tcl()
    clocks=[NATIVE,MEMORY,SDRAM,HDMI,'sysmem|h2f_user0_clk']
    regs=['emu|v8_video|rgb[0]','cpu|data[0]']
    if enabled:
        clocks.append(TV)
        regs+=['emu|pds_bridge|'+name for name in ('command_payload[0]','response_payload[0]',
                'source_readdata[0]','reading','address[0]','writedata[0]','byteenable[0]',
                'request_meta','acknowledge_meta')]
        regs+=['emu|crt_tv|canvas|line_payload[0]',STORE+'bank',STORE+'address[0]',STORE+'read_words[0]',STORE+'pair_meta']
        for name in ('wr_gray','rd_gray','wr_gray_meta','rd_gray_meta'):
            regs+=[FIFO+name+f'[{i}]' for i in range(11)]
    if missing: regs=[r for r in regs if missing not in r]
    calls=[]
    clock_ids={f'clk_{i}':clock for i,clock in enumerate(clocks)}
    def items(value): return list(t.splitlist(value))
    def objects(values,*args):
        args=[a for a in args if a not in ('-nowarn','-compatibility_mode')]
        assert len(args)<=1,args
        patterns=items(args[0]) if args else ['*']
        return tuple(v for v in values if any(re.fullmatch(re.escape(p).replace(r'\*','.*'),v) for p in patterns))
    for name,values in [('get_registers',regs),('get_keepers',regs),('get_clocks',clocks),
                        ('get_ports',['VGA_R[0]']),('get_pins',['emu|tv_reset_pipe[0]|clrn','emu|crt_tv|canvas|store|clk'])]:
        t.createcommand(name,lambda *a,values=values:objects(values,*a))
    t.createcommand('get_collection_size',lambda a:len(items(a)))
    t.createcommand('remove_from_collection',lambda a,b:tuple(x for x in items(a) if x not in items(b)))
    t.createcommand('add_to_collection',lambda a,b:tuple(dict.fromkeys(items(a)+items(b))))
    def clock_info(option,clock):
        clock=clock_ids.get(clock,clock)
        if option=='-name': return clock
        if option=='-period': return 1000/65 if clock==MEMORY else 1000/32.5
        assert option=='-targets'
        return (clock,)
    def fanouts(*args):
        clock=items(args[-1])[0]
        if clock==NATIVE: return tuple(r for r in regs if r.startswith('emu|v8_video') or r.startswith(FIFO+'wr_gray[') or r.startswith(FIFO+'rd_gray_meta['))
        if clock==MEMORY: return tuple(r for r in regs if r.startswith(STORE) or r.startswith(FIFO+'rd_gray[') or r.startswith(FIFO+'wr_gray_meta['))
        return ('cpu|data[0]',)
    t.createcommand('get_clock_info',clock_info)
    t.createcommand('get_fanouts',fanouts)
    def collection_ids(collection):
        ids={clock:identifier for identifier,clock in clock_ids.items()}
        return tuple(ids.get(value,value) for value in items(collection))
    t.createcommand('collection_ids',collection_ids)
    t.eval('proc foreach_in_collection {var collection body} {uplevel 1 [list foreach $var [collection_ids $collection] $body]}')
    for command in ('set_false_path','set_clock_groups','set_max_delay','set_min_delay','set_max_skew',
                    'set_multicycle_path','create_generated_clock','set_input_delay','set_output_delay'):
        t.createcommand(command,lambda *args,command=command:calls.append((command,args)) or '')
    try: t.eval((ROOT/'MacLC.sdc').read_text())
    except tkinter.TclError as error:
        if missing and ('Gray synchronizer heads missing' in str(error) or 'Gray endpoints missing' in str(error) or 'held-line mailbox endpoint missing' in str(error) or 'Ethernet CDC payload endpoints missing' in str(error)):
            print('PASS missing endpoint rejected:',missing)
            return
        raise
    assert not missing,'Missing endpoint accepted'
    if enabled:
        for source,dest in [(FIFO+'wr_gray[0]',FIFO+'wr_gray_meta[0]'),(FIFO+'rd_gray[0]',FIFO+'rd_gray_meta[0]')]:
            assert any(c=='set_max_delay' and a[0]=='8.0' and source in items(a[2]) and dest in items(a[4]) for c,a in calls)
            assert any(c=='set_max_skew' and a[0]=='8.0' and source in items(a[2]) and dest in items(a[4]) for c,a in calls)
            for command,args in calls:
                if command=='set_false_path' and '-hold' not in args and '-from' in args and '-to' in args:
                    assert not (source in items(args[args.index('-from')+1]) or dest in items(args[args.index('-to')+1])),args
        assert t.eval('set fifo_memory_clocks')==MEMORY
    print('PASS timing constraints:', '480i' if enabled else 'native')

check(False)
check(True)
check(True,'rd_gray_meta[')
check(True,STORE+'bank')

check(True,"command_payload[")
