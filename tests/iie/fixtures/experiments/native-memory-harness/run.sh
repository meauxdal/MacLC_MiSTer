#!/bin/sh
set -eu
maclc_root=${1:-/mnt/c/Workspace/Git/MacLC_MiSTer}
out=local/experiments/native-memory-harness
sources="fixtures/experiments/memory-harness/card_memory_arbiter.sv fixtures/experiments/native-memory-harness/card_native_memory_adapter.sv fixtures/experiments/native-memory-harness/tb_native_memory.sv"
mkdir -p "$out"
iverilog -g2012 -DTB_NO_TRISTATE -s tb_native_memory -o "$out/native.vvp" $sources "$maclc_root/rtl/sdram.v"
vvp "$out/native.vvp" > "$out/simulation.log"
cat "$out/simulation.log"
verilator --lint-only --top-module card_native_memory_adapter fixtures/experiments/native-memory-harness/card_native_memory_adapter.sv > "$out/adapter-lint.log" 2>&1
verilator --lint-only --timing -Wno-fatal -DTB_NO_TRISTATE --top-module tb_native_memory $sources "$maclc_root/rtl/sdram.v" > "$out/native-lint.log" 2>&1
cat "$out/native-lint.log"
