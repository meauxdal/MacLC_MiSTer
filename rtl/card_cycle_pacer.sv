// CPU cycle pacing against a free-running clock. Credit accrues every clock
// at the cycle rate; each completed cycle spends one cycle's worth. A cycle
// held up by a slow memory response keeps its credit, so the next cycles
// catch up and the long-run rate stays locked to the 14.318 MHz disk clock.
// The debt is capped so a long pause or host stall cannot bank a long burst.
module card_cycle_pacer #(
    parameter integer CLOCK_HZ = 65000000,
    parameter integer NORMAL_HZ = 1022727, // 14.318182 MHz / 14, as a IIe
    parameter integer FAST_HZ = 1900000,
    parameter integer MAX_DEBT = 16        // cycles of catch-up credit
) (
    input wire clk,
    input wire reset,
    input wire fast,
    input wire complete,
    output wire due
);
    localparam [31:0] LIMIT = 32'(CLOCK_HZ) * 32'(MAX_DEBT + 1);
    reg [31:0] phase;
    reg selected_fast;
    wire [31:0] rate = selected_fast ? FAST_HZ : NORMAL_HZ;
    wire spend = complete && due;
    wire [31:0] base = spend ? phase - 32'(CLOCK_HZ) : phase;
    wire [32:0] next_phase = {1'b0, base} + {1'b0, rate};
    assign due = !reset && phase >= 32'(CLOCK_HZ);

    generate if (CLOCK_HZ <= 0 || NORMAL_HZ <= 0 || FAST_HZ <= 0 ||
            NORMAL_HZ > CLOCK_HZ || FAST_HZ > CLOCK_HZ || MAX_DEBT < 0 ||
            64'(CLOCK_HZ) * 64'(MAX_DEBT + 2) >= 64'h1_0000_0000) begin : invalid_rates
        initial $fatal(1, "rates must be positive, no greater than CLOCK_HZ, and the debt must fit");
    end endgenerate

    always @(posedge clk) begin
        if (reset) begin
            phase <= 0;
            selected_fast <= fast;
        end else begin
            phase <= next_phase > {1'b0, LIMIT} ? LIMIT : next_phase[31:0];
            if (spend) begin
                selected_fast <= fast;
                if (fast != selected_fast) phase <= 0;
            end
        end
    end
endmodule
