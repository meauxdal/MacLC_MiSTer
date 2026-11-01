module card_display_state #(
    // This reset policy is a model input, not a measured card power-up state.
    parameter [7:0] RESET_STATE = 8'h00
) (
    input wire clk,
    input wire reset,
    input wire valid,
    input wire complete,
    input wire [15:0] address,
    input wire write,
    input wire aux,
    input wire double_hires,
    input wire motor,
    output wire altchar,
    output wire text_mode,
    output wire hires,
    output wire annunciator3,
    output wire col80,
    output wire mixed,
    output wire page2,
    output wire store80,
    output wire active_page2,
    output wire text_page_active,
    output wire hires_page_active,
    output wire display_trap,
    output wire io_trap
);
    reg [7:0] state;
    wire full_graphics = !text_mode && !mixed;
    assign {store80, page2, mixed, col80, annunciator3, hires, text_mode, altchar} = state;
    assign active_page2 = page2 && !store80;
    // Whole-page eligibility; mixed-mode scanline filtering is caller-owned.
    assign text_page_active = text_mode || !hires || mixed;
    assign hires_page_active = !text_mode && hires;

    always @(posedge clk) begin
        if (reset) state <= RESET_STATE;
        else if (valid && complete) begin
            case (address)
                16'hC000, 16'hC001: if (write) state[7] <= address[0];
                16'hC00C, 16'hC00D: if (write) state[4] <= address[0];
                16'hC00E, 16'hC00F: if (write) state[0] <= address[0];
                16'hC050, 16'hC051: state[1] <= address[0];
                16'hC052, 16'hC053: state[5] <= address[0];
                16'hC054, 16'hC055: state[6] <= address[0];
                16'hC056, 16'hC057: state[2] <= address[0];
                16'hC05E, 16'hC05F: state[3] <= address[0];
                default: ;
            endcase
        end
    end

    card_trap_decode decode (
        .valid(valid && !reset), .address(address), .write(write), .aux(aux),
        .text_active(text_page_active), .text_page2(active_page2),
        .hires_active(hires_page_active), .hires_page2(active_page2),
        .col80(col80), .full_graphics(full_graphics),
        .double_hires(double_hires), .motor(motor),
        .display_trap(display_trap), .io_trap(io_trap)
    );
endmodule
