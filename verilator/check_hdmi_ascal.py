"""Actual ASCAL + TV arbiter functional regression. Requires GHDL and Verilator; no Quartus."""
from pathlib import Path
import re
import hashlib
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
p = root / "scratch/hdmi_ascal_regression"
p.mkdir(parents=True, exist_ok=True)
for program in ("ghdl", "verilator"):
    if not shutil.which(program):
        raise SystemExit(f"Required simulation tool missing: {program}")
source = root / "sys/ascal.vhd"
key = hashlib.sha256(source.read_bytes() + b"RAMBASE=20000000 N_AW=28 PALETTE2=false FRAC=8 v1").hexdigest()
stamp = p / "source.sha256"
if not (p / "ascal.v").exists() or not stamp.exists() or stamp.read_text() != key:
    subprocess.run(["ghdl", "-a", "--std=08", str(source)], cwd=p, check=True)
    with (p / "ascal.v").open("w") as output, (p / "synth.log").open("w") as log:
        subprocess.run(["ghdl", "--synth", "--std=08", "--out=verilog",
                        "-gRAMBASE=00100000000000000000000000000000", "-gN_AW=28",
                        "-gPALETTE2=false", "-gFRAC=8", "ascal"],
                       cwd=p, stdout=output, stderr=log, check=True)
    stamp.write_text(key)
s=(p/'ascal.v').read_text().split(');',1)[0]
ports=re.findall(r'(input|output)\s+(\[[^]]+\]\s*)?(\w+)',s)
mem={'avl_waitrequest','avl_readdata','avl_readdatavalid','avl_burstcount','avl_writedata','avl_address','avl_write','avl_read','avl_byteenable'}
# Keep real scaler intact; expose all its other ports, add bypass and TV traffic.
header=[f'{d} wire {w or ""}{n}' for d,w,n in ports if n not in mem]
header += ['input wire bypass, tv_read','input wire waitrequest, readdatavalid','input wire [127:0] readdata','output wire [27:0] address','output wire [7:0] burstcount','output wire [127:0] writedata','output wire [15:0] byteenable','output wire read, write']
body=['module hdmi_fixture('+',\n'.join(header)+');']
body += [f'wire {w or ""}{n};' for d,w,n in ports if n in mem]
body += ['ascal scaler('+','.join(f'.{n}({n})' for d,w,n in ports)+');']
body += ['wire a_wait, a_valid; wire [127:0] a_data; wire [27:0] arb_addr; wire [7:0] arb_count; wire [127:0] arb_data; wire [15:0] arb_be; wire arb_read,arb_write;']
body += ['''tv_ddr_arbiter arb(.clk(avl_clk),.inhibit(~reset_na),
.a_address(avl_address),.a_burstcount(avl_burstcount),.a_writedata(avl_writedata),.a_byteenable(avl_byteenable),.a_read(avl_read & ~bypass),.a_write(avl_write & ~bypass),.a_waitrequest(a_wait),.a_readdatavalid(a_valid),.a_readdata(a_data),
.b_address(28'h2180000),.b_burstcount(8'd160),.b_writedata(128'd0),.b_byteenable(16'hffff),.b_read(tv_read & ~bypass),.b_write(1'b0),.b_waitrequest(),.b_readdatavalid(),.b_readdata(),
.address(arb_addr),.burstcount(arb_count),.writedata(arb_data),.byteenable(arb_be),.read(arb_read),.write(arb_write),.waitrequest(waitrequest),.readdatavalid(readdatavalid),.readdata(readdata));
assign avl_waitrequest=bypass?waitrequest:a_wait;
assign avl_readdatavalid=bypass?readdatavalid:a_valid;
assign avl_readdata=bypass?readdata:a_data;
assign address=bypass?avl_address:arb_addr;
assign burstcount=bypass?avl_burstcount:arb_count;
assign writedata=bypass?avl_writedata:arb_data;
assign byteenable=bypass?avl_byteenable:arb_be;
assign read=bypass?avl_read:arb_read;
assign write=bypass?avl_write:arb_write;
endmodule''']
(p/'hdmi_fixture.sv').write_text('\n'.join(body))

negative = "--negative-control" in sys.argv[1:]
arbiter = root / "rtl/tv_ddr_arbiter.sv"
obj = "obj"
if negative:
    # Corrupt scaler receive-byte alignment without changing production RTL.
    faulty = arbiter.read_text().replace(
        "assign a_readdata = readdata;",
        "assign a_readdata = {readdata[119:0], readdata[127:120]};")
    assert faulty != arbiter.read_text()
    arbiter = p / "negative_arbiter.sv"
    arbiter.write_text(faulty)
    obj = "obj_negative"
with (p / ("build_negative.log" if negative else "build.log")).open("w") as log:
    subprocess.run(["verilator", "--cc", "--exe", "--build", "-j", "4", "-Wno-fatal",
                    "--top-module", "hdmi_fixture", "--Mdir", obj, "-o", "test",
                    "-CFLAGS", "-std=c++17 -O2", "hdmi_fixture.sv", "ascal.v",
                    str(arbiter), str(root / "verilator/tb_hdmi_ascal.cpp")],
                   cwd=p, stdout=log, stderr=log, check=True)
result = subprocess.run([str(p / obj / "test")], cwd=p, capture_output=True, text=True)
(p / ("run_negative.log" if negative else "run.log")).write_text(result.stdout + result.stderr)
print(result.stdout + result.stderr, end="")
if negative:
    assert result.returncode != 0 and "progressive HDMI pixel/sync mismatch" in result.stderr
    print("PASS negative control: corrupt scaler receive-byte alignment detected")
else:
    result.check_returncode()
