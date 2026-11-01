// Startup 1.0 access eligibility from Apple IIe Technical Note 10.
module card_trap_decode (
    input wire valid,
    input wire [15:0] address,
    input wire write,
    input wire aux,
    input wire text_active,
    input wire text_page2,
    input wire hires_active,
    input wire hires_page2,
    input wire col80,
    input wire full_graphics,
    input wire double_hires,
    input wire motor,
    output wire display_trap,
    output wire io_trap
);
    // Active pages and the physical main/aux selection are caller-owned.
    wire text_hit = text_active && (text_page2
        ? address[15:10] == 6'h02 : address[15:10] == 6'h01);
    wire hires_hit = hires_active && (hires_page2
        ? address[15:13] == 3'b010 : address[15:13] == 3'b001);
    wire screen_byte = address[6:3] != 4'hF;
    wire both_directions = (address >= 16'hC050 && address <= 16'hC05F) ||
                           address == 16'hC070 ||
                           (address >= 16'hC090 && address <= 16'hC0DF) ||
                           address == 16'hC0E8 || address == 16'hC0E9 ||
                           (address >= 16'hC0F0 && address <= 16'hC0FF) ||
                           address == 16'hCFFF;
    wire writes_only = address == 16'hC000 || address == 16'hC001 ||
                       (address >= 16'hC00C && address <= 16'hC00F);

    assign display_trap = valid && write && !motor && screen_byte &&
        ((text_hit && (!aux || (col80 && !full_graphics))) ||
         (hires_hit && (!aux || double_hires)));
    assign io_trap = valid && (both_directions || (write && writes_only));
endmodule
