#!/bin/sh
set -eu
out=local/experiments/native-memory-harness
mux=fixtures/experiments/native-memory-harness/card_native_port_mux.sv
bench=fixtures/experiments/native-memory-harness/tb_native_port_mux.sv
mkdir -p "$out"
iverilog -g2012 -s tb_native_port_mux -o "$out/mux.vvp" "$mux" "$bench"
vvp "$out/mux.vvp" > "$out/mux-simulation.log"
cat "$out/mux-simulation.log"
verilator --lint-only --timing --top-module tb_native_port_mux "$mux" "$bench" > "$out/mux-lint.log" 2>&1
cat "$out/mux-lint.log"
