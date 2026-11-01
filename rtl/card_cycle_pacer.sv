// Completion spacing. Overdue cycles do not accumulate future enables.
module card_cycle_pacer #(
    parameter integer CLOCK_HZ = 65000000,
    parameter integer NORMAL_HZ = 1020000,
    parameter integer FAST_HZ = 1900000
) (
    input wire clk,
    input wire reset,
    input wire fast,
    input wire complete,
    output wire due
);
    reg [31:0] phase;
    reg overdue, selected_fast;
    wire [31:0] rate = selected_fast ? FAST_HZ : NORMAL_HZ;
    wire [32:0] next_phase = {1'b0, phase} + {1'b0, rate};
    assign due = !reset && (overdue || next_phase >= {1'b0, 32'(CLOCK_HZ)});

    generate if (CLOCK_HZ <= 0 || NORMAL_HZ <= 0 || FAST_HZ <= 0 ||
            NORMAL_HZ > CLOCK_HZ || FAST_HZ > CLOCK_HZ) begin : invalid_rates
        initial $fatal(1, "rates must be positive and no greater than CLOCK_HZ");
    end endgenerate

    always @(posedge clk) begin
        if (reset) begin
            phase <= 0;
            overdue <= 0;
            selected_fast <= fast;
        end else if (complete && due) begin
            phase <= overdue ? 0 : 32'(next_phase - CLOCK_HZ);
            overdue <= 0;
            selected_fast <= fast;
            if (fast != selected_fast) phase <= 0;
        end else if (!overdue) begin
            if (due) overdue <= 1;
            else phase <= next_phase[31:0];
        end
    end
endmodule
