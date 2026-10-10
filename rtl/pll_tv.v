// Independent 50 MHz -> 27 MHz TV clock.
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
