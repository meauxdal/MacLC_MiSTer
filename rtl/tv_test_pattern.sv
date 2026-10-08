// Combinational diagnostic picture in logical square-pixel canvas coordinates.
// Hold pattern/geometry constant for a field pair; a platform wrapper should
// latch user controls at frame_start. This module never changes raster timing.
// geometry: 0=640x480, 1=512x384, 2=512x342, 3=640x480 (reserved fallback).
// pattern: 0=black, 1=white, 2=ramp, 3=75% bars, 4=grid/circle,
//          5=field patch, 6=alternating lines, 7=source-coordinate signature.
module tv_test_pattern (
    input  wire        picture_de,
    input  wire [9:0]  canvas_x,
    input  wire [8:0]  canvas_y,
    input  wire        field_id,
    input  wire [2:0]  pattern,
    input  wire [1:0]  geometry,
    output reg  [23:0] rgb,
    output wire        image_de
);

wire small_image = (geometry == 2'd1) || (geometry == 2'd2);
wire [9:0] left = small_image ? 10'd64 : 10'd0;
wire [8:0] top = (geometry == 2'd2) ? 9'd69 :
                (geometry == 2'd1) ? 9'd48 : 9'd0;
wire [8:0] bottom = (geometry == 2'd2) ? 9'd411 :
                   (geometry == 2'd1) ? 9'd432 : 9'd480;
assign image_de = picture_de && (canvas_x >= left) &&
                 (canvas_x < (small_image ? 10'd576 : 10'd640)) &&
                 (canvas_y >= top) && (canvas_y < bottom);
wire [9:0] source_x = canvas_x - left;
wire [8:0] source_y = canvas_y - top;

wire signed [10:0] dx = $signed({1'b0, canvas_x}) - 11'sd320;
wire signed [10:0] dy = $signed({2'b00, canvas_y}) - 11'sd240;
wire [21:0] dx_squared = dx * dx;
wire [21:0] dy_squared = dy * dy;
wire [22:0] radius_squared = {1'b0, dx_squared} + {1'b0, dy_squared};
wire circle = (radius_squared >= 23'd25344) && (radius_squared <= 23'd25856);
wire grid = (canvas_x[4:0] == 5'd0) || (canvas_y[4:0] == 5'd0);
wire edge_mark = (canvas_x < 10'd2) || (canvas_x >= 10'd638) ||
                 (canvas_y < 9'd2) || (canvas_y >= 9'd478);
// Full-canvas ramp and bars make picture-aperture changes visible. The
// coordinate pattern instead identifies native source rows/columns in borders.
wire [7:0] ramp = 8'((32'(canvas_x) * 255) / 639);

always @* begin
    rgb = 24'd0;
    if (image_de) begin
        case (pattern)
            3'd0: rgb = 24'h000000;
            3'd1: rgb = 24'hffffff;
            3'd2: rgb = {ramp, ramp, ramp};
            3'd3: begin
                if      (canvas_x < 10'd80)  rgb = 24'hbfbfbf;
                else if (canvas_x < 10'd160) rgb = 24'hbfbf00;
                else if (canvas_x < 10'd240) rgb = 24'h00bfbf;
                else if (canvas_x < 10'd320) rgb = 24'h00bf00;
                else if (canvas_x < 10'd400) rgb = 24'hbf00bf;
                else if (canvas_x < 10'd480) rgb = 24'hbf0000;
                else if (canvas_x < 10'd560) rgb = 24'h0000bf;
                else                       rgb = 24'h000000;
            end
            3'd4: begin
                rgb = 24'h101010;
                if (grid) rgb = 24'h606060;
                if (circle) rgb = 24'hffffff;
                if ((canvas_x == 10'd320) || (canvas_y == 9'd240)) rgb = 24'hffff00;
                if (edge_mark) rgb = 24'h00ff00;
            end
            3'd5: begin
                rgb = 24'h404040;
                if ((canvas_x >= 10'd288) && (canvas_x < 10'd352) &&
                    (canvas_y >= 9'd208) && (canvas_y < 9'd272))
                    rgb = field_id ? 24'h00ffff : 24'hff0000;
            end
            3'd6: rgb = canvas_y[0] ? 24'h000000 : 24'hffffff;
            3'd7: rgb = {source_y[7:0], source_x[7:0],
                         source_y[8], source_x[9:8], 5'b10101};
            default: rgb = 24'h000000;
        endcase
    end
end

endmodule
