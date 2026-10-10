// Independent integer-N TV clock. The Quartus PLL solver must produce exact
// 50 MHz -> 27 MHz; one legal solution is M=27,N=2,C=25,VCO=675 MHz.
// No reconfiguration or dependency on the native Mac video PLL.
// Compensate the internal clock network: the TV clock-to-pin budget includes
// launch latency, and direct mode left 4.435 ns before Q in the 20:41 fit.
// Normal mode changes the physical feedback/clock alignment; the 27 MHz
// frequency, zero requested phase and SDC output budget remain unchanged.
`timescale 1 ps / 1 ps
module pll_tv (
    input wire refclk, rst,
    output wire outclk_0, locked
);
altera_pll #(
    .fractional_vco_multiplier("false"),
    .reference_clock_frequency("50.0 MHz"),
    .operation_mode("normal"),
    .number_of_clocks(1),
    .output_clock_frequency0("27.000000 MHz"),
    .phase_shift0("0 ps"), .duty_cycle0(50),
    .pll_type("General"), .pll_subtype("General")
) altera_pll_i (
    .refclk(refclk), .rst(rst), .outclk(outclk_0), .locked(locked),
    .fbclk(1'b0), .fboutclk()
);
endmodule
