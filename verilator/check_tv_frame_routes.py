"""Preprocess both CRT configurations and preserve all unrelated sys_top branches."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
baseline = root / "scratch/tv_frame_routes_baseline.v"
# Last TV-only revision, before the optional analog selector. HEAD is not a
# stable oracle once the change being tested has been committed.
baseline.write_bytes(subprocess.check_output(["git", "show", "70229a3:sys/sys_top.v"], cwd=root))
# Preprocess without altering the real build stamp; this fixture is never built.
(root / "scratch/build_id.v").write_text('localparam BUILD_DATE = "261008";\n')

def preprocess(path, defines):
    value = subprocess.check_output(["verilator", "-E", "-P", "+incdir+"+str(root/"sys"), "+incdir+"+str(root/"scratch"),
                                     *("+define+"+d for d in defines), str(path)], text=True, cwd=root)
    value = re.sub(r"/\*.*?\*/|//[^\n]*", "", value, flags=re.S)
    return re.sub(r"\s+", "", value)

for defines in [[], ["MISTER_DEBUG_NOHDMI"], ["MISTER_DISABLE_VGA_OSD"],
                ["MAC_384P_TEST", "MISTER_DEBUG_NOHDMI"],
                ["MAC_480I_TEST", "MISTER_DEBUG_NOHDMI"], ["MISTER_DUAL_SDRAM"]]:
    assert preprocess(baseline, defines) == preprocess(root/"sys/sys_top.v", defines), defines
    print("PASS unchanged sys_top branch:", defines or "normal")

for defines in [["MAC_TV525_DIAG", "MISTER_DEBUG_NOHDMI"], ["MAC_TV525_DIAG"]]:
    value = preprocess(root/"sys/sys_top.v", defines)
    for required in ["tv525_platform#(.BUFFERED(1))crt_tv(", "tv_ddr_arbitertv_vbuf_arbiter(",
                     "wirecs1=tv_analog_enable?(tv525_drive?tv525_cs_n:1'b1):(vgas_en?vgas_cs:vga_cs);",
                     "wire[1:0]vga_r=tv_analog_enable?tv525_low_r:",
                     "assignVGA_HS=tv_analog_enable?(tv525_drive?tv525_hs_n:1'bZ):",
                     ".TV_ANALOG_ENABLE(tv_analog_request)",
                     "tv_analog_meta<=tv_analog_request;tv_analog_enable<=tv_analog_meta;",
                     ".TV_NATIVE_RGB(tv_native_rgb)", ".source_ce(ce_pix)",
                     ".b_address(tv_store_address)", ".address(vbuf_address)"]:
        assert required in value, required
    assert "osdvga_osd(" in value and "mac_interlacerinterlacer(" not in value
    assert ".osd_status(native_osd_status)" in value
    assert ".osd_status(tv_osd_status)" in value
    assert "assignosd_status=tv_analog_enable?tv_osd_status:native_osd_status;" in value
    normal = preprocess(baseline, [d for d in defines if d != "MAC_TV525_DIAG"])
    previous_tv = preprocess(baseline, defines)
    # Every native pin expression is exactly the pre-existing analog route.
    for pin in ("VGA_VS", "VGA_HS", "VGA_R", "VGA_G", "VGA_B"):
        original = re.search("assign"+pin+r"=(.*?);", normal)[1]
        selected = re.search("assign"+pin+r"=tv_analog_enable\?\(.*?\):(.*?);", value)[1]
        assert selected == original, (pin, selected, original)
        tv_selected = re.search("assign"+pin+r"=tv_analog_enable\?\((.*?)\):", value)[1]
        assert tv_selected == re.search("assign"+pin+r"=(.*?);", previous_tv)[1], pin
    for pin in ("vga_r", "vga_g", "vga_b"):
        original = re.search(r"wire\[1:0\]"+pin+r"=(.*?);", normal)[1]
        selected = re.search(r"wire\[1:0\]"+pin+r"=tv_analog_enable\?tv525_low_[rgb]:(.*?);", value)[1]
        assert selected == original, pin
    for signal in ("cs1", "de1"):
        selected = re.search("wire"+signal+r"=tv_analog_enable\?\(.*?\):\((.*?)\);", value)[1]
        assert selected == re.search("wire"+signal+r"=(.*?);", normal)[1], signal
    assert "assign{SDIO_CLK,SDIO_CMD,SDIO_DAT}=(av_dis|((mcp_en|sd_cd)&tv_analog_enable&~tv525_drive))?6'bZZZZZZ:(mcp_en|sd_cd)?{vga_g,vga_r,vga_b}:{SD_CLK,SD_MOSI,SD_CS,3'bZZZ};" in value
    if "MISTER_DEBUG_NOHDMI" in defines:
        assert "assignnative_vga_tx_clk=clk_vid;" in value
    else:
        assert "cyclonev_clkselectvga_clk_sw(.clkselect({1'b1,~vga_fb&~vga_scaler}),.inclk({clk_vid,hdmi_clk_out,2'b00}),.outclk(native_vga_tx_clk));" in value
    assert "assignvga_tx_clk=tv_analog_enable?clk_tv525:native_vga_tx_clk;" in value
    assert value.count(".outclock(vga_tx_clk)") == 1
    assert value.count("vga_tx_clk") == 6  # three uses each of native/selected clock
    # Quartus 15836: inclk[0:1] cannot be driven by a PLL clock.
    for inputs in re.findall(r"cyclonev_clkselect\w+\(.*?\.inclk\(\{(.*?)\}\)", value):
        assert inputs.endswith("2'b00"), inputs
    if "MISTER_DEBUG_NOHDMI" in defines:
        assert "assignscaler_read=0;" in value and "ascal#(" not in value
    else:
        assert "ascal#(" in value and ".avl_address(scaler_address)" in value
        assert ".avl_address(vbuf_address)" not in value
    print("PASS buffered TV routes and exclusive/arbitrated vbuf ownership:", defines)

emu = preprocess(root/"MacLC.sv", ["MAC_TV525_DIAG"])
for required in ["tv_deflickercrt_filter(", ".rgb({v8_vga_r,v8_vga_g,v8_vga_b})",
                 ".out_reset(TV_NATIVE_RESET)", ".out_rgb(TV_NATIVE_RGB)",
                 ".mode(tv_filter_sync)", "tv_filter_meta<=tv_filter_mode;",
                 "O3,AnalogOutput,Native,480i;", "assignTV_ANALOG_ENABLE=status[3];",
                 "O12,CRTDe-flicker,Strong,Mild,Off;",
                 "wire[1:0]tv_filter_mode=status[2:1]==2'd0?2'd2:status[2:1]==2'd1?2'd1:status[2:1]==2'd2?2'd0:2'd2;",
                 ".native_frame_start(native_frame_start)"]:
    assert required in emu, required
assert "tv_deflicker" not in preprocess(root/"MacLC.sv", [])
print("PASS CRT-only filtered V8 tap before overlays; normal profile excludes filter")

tv = preprocess(root/"sys/sys_top.v", ["MAC_TV525_DIAG"])
normal = preprocess(baseline, [])
for pin in ("HDMI_TX_CLK", "HDMI_TX_DE", "HDMI_TX_D", "HDMI_TX_HS", "HDMI_TX_VS"):
    assert re.findall("assign"+pin+r"=.*?;", tv) == re.findall("assign"+pin+r"=.*?;", normal), pin
print("PASS unchanged HDMI pin routes alongside ASCAL in TV profile")

# Check the whole native/HDMI path, not merely the final pin assignments.
# DDR arbitration is the deliberate exception and is exercised by
# check_hdmi_ascal.py using the actual ASCAL VHDL.
def instance(value, name):
    # Preprocessing removes whitespace, so locate the instance suffix instead.
    start = value.index(name + "(") + len(name)
    depth, end = 0, start
    while end < len(value):
        if value[end] == "(": depth += 1
        if value[end] == ")":
            depth -= 1
            if depth == 0: return value[start:end + 1]
        end += 1
    raise AssertionError("Unterminated instance: " + name)

for name in ("ascal", "HDMI_shadowmask", "hdmi_osd", "VGA_scanlines",
             "sync_v", "sync_h", "hdmi_clk_sw", "hdmiclk_ddr"):
    actual = instance(tv, name)
    if name == "ascal":
        for suffix in ("address", "burstcount", "writedata", "byteenable", "read",
                       "write", "waitrequest", "readdata", "readdatavalid"):
            actual = actual.replace("scaler_" + suffix, "vbuf_" + suffix)
    assert actual == instance(normal, name), name
for signal in ("clk_ihdmi", "ce_hpix", "hr_out", "hg_out", "hb_out",
               "hhs_fix", "hvs_fix", "hde_emu"):
    assert re.findall("assign" + signal + r"=.*?;", tv) == re.findall("assign" + signal + r"=.*?;", normal), signal
for first, last in (("reg[23:0]dv_data;", "assignHDMI_TX_D=hdmi_out_d;"),):
    # Includes direct-video source, clock selection, output mux and registers.
    assert tv[tv.index(first):tv.index(last)] == normal[normal.index(first):normal.index(last)]
native_emu = preprocess(root/"MacLC.sv", [])
for signal in ("CLK_VIDEO", "CE_PIXEL", "VGA_R", "VGA_G", "VGA_B",
               "VGA_DE", "VGA_HS", "VGA_VS", "VGA_F1", "VGA_SL",
               "HDMI_FREEZE", "HDMI_BLACKOUT", "HDMI_BOB_DEINT"):
    assert re.findall("assign" + signal + r"=.*?;", emu) == re.findall("assign" + signal + r"=.*?;", native_emu), signal
assert ".HPS_BUS({f1,HDMI_TX_VS,clk_100m,clk_ihdmi,ce_hpix,hde_emu,hhs_fix,hvs_fix," in tv
print("PASS native HDMI source, CE/clock, field/deinterlace, scaler controls, direct-video and OSD path")
mem_baseline = root / "scratch/tv_sysmem_baseline.sv"
mem_baseline.write_bytes(subprocess.check_output(["git", "show", "70229a3:sys/sysmem.sv"], cwd=root))
assert preprocess(mem_baseline, []) == preprocess(root/"sys/sysmem.sv", [])
assert "vbuf_open_cnt" in preprocess(root/"sys/sysmem.sv", ["MAC_TV525_DIAG"])
print("PASS normal sysmem unchanged; TV startup gate enabled")
