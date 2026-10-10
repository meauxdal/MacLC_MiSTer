"""Check standard core routes and reject local framework changes."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
subprocess.run(['git','diff','--exit-code','upstream/master','--','sys'],cwd=ROOT,check=True)

def preprocess(enabled):
    with tempfile.TemporaryDirectory() as folder:
        # The Quartus pre-flow generates this file; lint uses a fixed fixture.
        Path(folder,'build_id.v').write_text('`define BUILD_DATE "000000"\n')
        command=['verilator','-E','-I'+folder]
        if enabled: command.append('-DMAC_TV525_DIAG')
        command.append('MacLC.sv')
        text=subprocess.check_output(command,cwd=ROOT,text=True)
        text=re.sub(r'//[^\n]*|/\*.*?\*/','',text,flags=re.S)
        return re.sub(r'\s+','',text)

tv=preprocess(True)
native=preprocess(False)
for required in ('assignCLK_VIDEO=clk_tv525;', "assignCE_PIXEL=1'b1;",
                 'assign{VGA_R,VGA_G,VGA_B}=tv_rgb;', 'assignVGA_F1=tv_field;',
                 'tv525_videocrt_tv(', 'tv_ddram_bridgetv_bridge(',
                 'tv_ddr_arbiter#(.DW(64),.AW(29))tv_ram_arbiter(',
                 '.mem_rvalid(pds_mem_rvalid)', '.source_ce(v8_ce_pix)', 'assignDDRAM_CLK=clk_mem;', 'tv_ddram_cdcpds_bridge('):
    assert required in tv,required
for forbidden in ('TV_NATIVE_', 'TV_ANALOG_ENABLE', 'LFB_', 'tv_component', 'tv_osd', 'AnalogOutput,Native,480i'):
    assert forbidden not in tv,forbidden
for required in ('assignCLK_VIDEO=clk_vid;', 'assignCE_PIXEL=v8_ce_pix;',
                 'assignVGA_F1=0;', 'assignDDRAM_RD=pds_mem_rd;', '.mem_rvalid(DDRAM_DOUT_READY)'):
    assert required in native,required
assert 'tv525_videocrt_tv(' not in native
for name in ('MacLC.qsf','files.qip'):
    sources=(ROOT/name).read_text()
    for rtl in ('tv525_video.sv','tv_ddram_bridge.sv'):
        assert 'rtl/'+rtl in sources
    for rtl in ('tv525_platform.sv','tv525_output.sv','tv_osd.sv','tv_component.sv','tv_component_pins.sv'):
        assert 'rtl/'+rtl not in sources
print('PASS stock framework, dedicated 480i routes, native build, DDRAM ownership and source lists')
