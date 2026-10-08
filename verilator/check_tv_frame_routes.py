"""Preprocess both CRT configurations and preserve all unrelated sys_top branches."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
baseline = root / "scratch/tv_frame_routes_baseline.v"
baseline.write_bytes(subprocess.check_output(["git", "show", "HEAD:sys/sys_top.v"], cwd=root))
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
                     "assignvga_tx_clk=clk_tv525;", "wirecs1=tv525_drive?tv525_cs_n:1'b1;",
                     "wire[1:0]vga_r=tv525_low_r;", "assignVGA_HS=tv525_drive?tv525_hs_n:1'bZ;",
                     ".TV_NATIVE_RGB(tv_native_rgb)", ".source_ce(ce_pix)",
                     ".b_address(tv_store_address)", ".address(vbuf_address)"]:
        assert required in value, required
    assert "osdvga_osd(" not in value and "mac_interlacerinterlacer(" not in value
    if "MISTER_DEBUG_NOHDMI" in defines:
        assert "assignscaler_read=0;" in value and "ascal#(" not in value
    else:
        assert "ascal#(" in value and ".avl_address(scaler_address)" in value
        assert ".avl_address(vbuf_address)" not in value
    print("PASS buffered TV routes and exclusive/arbitrated vbuf ownership:", defines)

emu = preprocess(root/"MacLC.sv", ["MAC_TV525_DIAG"])
for required in ["assignTV_NATIVE_RGB={v8_vga_r,v8_vga_g,v8_vga_b};", "assignTV_NATIVE_DE=v8_de;",
                 "assignTV_NATIVE_RESET=vidrst_s;", ".native_frame_start(native_frame_start)"]:
    assert required in emu, required
print("PASS emu exports raw V8 tap before video_freak and MT32/HUD/normal VGA overlays")

tv = preprocess(root/"sys/sys_top.v", ["MAC_TV525_DIAG"])
normal = preprocess(baseline, [])
for pin in ("HDMI_TX_CLK", "HDMI_TX_DE", "HDMI_TX_D", "HDMI_TX_HS", "HDMI_TX_VS"):
    assert re.findall("assign"+pin+r"=.*?;", tv) == re.findall("assign"+pin+r"=.*?;", normal), pin
print("PASS unchanged HDMI pin routes alongside ASCAL in TV profile")
mem_baseline = root / "scratch/tv_sysmem_baseline.sv"
mem_baseline.write_bytes(subprocess.check_output(["git", "show", "HEAD:sys/sysmem.sv"], cwd=root))
assert preprocess(mem_baseline, []) == preprocess(root/"sys/sysmem.sv", [])
assert "vbuf_open_cnt" in preprocess(root/"sys/sysmem.sv", ["MAC_TV525_DIAG"])
print("PASS normal sysmem unchanged; TV startup gate enabled")
