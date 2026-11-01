// Isolated candidate. Host arrival wins a simultaneous CPU clear.
module card_keyboard_candidate (
    input wire clk,
    input wire reset,
    input wire host_write,
    input wire [6:0] host_data,
    input wire cpu_complete,
    input wire [15:0] cpu_address,
    output reg [7:0] keyboard,
    output wire busy
);
    assign busy = keyboard[7];
    always @(posedge clk) begin
        if (reset) keyboard <= 0;
        else begin
            if (cpu_complete && cpu_address == 16'hC010) keyboard[7] <= 0;
            if (host_write) keyboard <= {1'b1, host_data};
        end
    end
endmodule
