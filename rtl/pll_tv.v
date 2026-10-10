// Independent 50 MHz -> 27 MHz TV clock.
`timescale 1 ps / 1 ps
module pll_tv (
    input wire refclk, rst,
    output wire outclk_0, locked
);
// The global reference route permits placement beyond the input pin's PLLs.
wire refclk_global;
altclkctrl #(
    .clock_type("Global Clock"), .number_of_clocks(1),
    .intended_device_family("Cyclone V")
) reference_clock (
    .inclk({3'b000,refclk}), .clkselect(2'b00), .ena(1'b1), .outclk(refclk_global)
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
    .refclk(refclk_global), .rst(rst), .outclk(outclk_0), .locked(locked),
    .fbclk(1'b0), .fboutclk()
);
endmodule
