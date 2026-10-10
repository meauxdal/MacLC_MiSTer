// Fixed 525-line / 59.94-field raster, one sample per 27 MHz clock.
// Electrical field 1 (line-1 origin) draws odd canvas rows (field_id=1).
// Electrical field 2 starts halfway through line 263 and draws even rows.
// field_id means SPATIAL row parity, not temporal field index (BT.1618 5.1.2).
// Sync is active low. csync_n is authoritative: do not recreate it by XOR
// of the HS/VS helpers. There is no source-video clock or frame-lock input.
module tv525_timing (
    input  wire        clk,
    input  wire        reset,       // synchronous reset; release in clk domain
    output wire        csync_n,
    output wire        hsync_n,     // regular line-rate helper, including VBI
    output wire        vsync_n,     // broad-sync envelope helper
    output wire        picture_de,
    output wire        pixel_ce,    // first DAC sample of each logical column
    output wire [9:0]  canvas_x,
    output wire [8:0]  canvas_y,
    output wire        field_id,
    output wire        frame_start,
    output wire        field_start,
    output wire        line_start,
    output wire        halfline_start,
    output wire [10:0] h_sample,
    output wire [9:0]  line_number  // standard electrical labels 1..525
);

localparam [9:0] HALF_SAMPLES = 10'd858;
localparam [10:0] FRAME_HALVES = 11'd1050;
localparam [10:0] FIELD_HALVES = 11'd525;
localparam [10:0] PICTURE_BEGIN = 11'd253;
localparam [10:0] PICTURE_END = 11'd1675;
localparam [11:0] PICTURE_SAMPLES = 12'd1422;

reg [9:0] half_sample = 10'd0;
reg [10:0] frame_half = 11'd0;
always @(posedge clk) begin
    if (reset) begin
        half_sample <= 10'd0;
        frame_half <= 11'd0;
    end else if (half_sample == HALF_SAMPLES - 10'd1) begin
        half_sample <= 10'd0;
        frame_half <= (frame_half == FRAME_HALVES - 11'd1) ?
                      11'd0 : frame_half + 11'd1;
    end else begin
        half_sample <= half_sample + 10'd1;
    end
end

wire second_field = (frame_half >= FIELD_HALVES);
assign field_id = !second_field;
wire [10:0] field_half = second_field ? frame_half - FIELD_HALVES : frame_half;
wire [9:0] line_index = frame_half[10:1];
assign line_number = line_index + 10'd1;
assign h_sample = {1'b0, half_sample} + (frame_half[0] ? 11'd858 : 11'd0);

wire equalizing = (field_half < 11'd6) ||
                  ((field_half >= 11'd12) && (field_half < 11'd18));
wire broad_sync = (field_half >= 11'd6) && (field_half < 11'd12);
wire sync_active = equalizing ? (half_sample < 10'd62) :
                   broad_sync ? (half_sample < 10'd731) :
                                (h_sample < 11'd127);
assign csync_n = reset || !sync_active;
assign hsync_n = reset || (h_sample >= 11'd127);
assign vsync_n = reset || !broad_sync;
assign halfline_start = !reset && (half_sample == 10'd0);
assign line_start = !reset && (h_sample == 11'd0);
assign field_start = halfline_start && (field_half == 11'd0);
assign frame_start = field_start && !second_field;

// Both apertures are located on the continuous line timeline, NOT at
// identical offsets from the two field origins (which are half a line apart).
wire active_line = second_field ? ((line_index >= 10'd284) && (line_index < 10'd524)) :
                                  ((line_index >= 10'd22) && (line_index < 10'd262));
wire active_sample = (h_sample >= PICTURE_BEGIN) && (h_sample < PICTURE_END);
assign picture_de = !reset && active_line && active_sample;
wire [7:0] picture_row = 8'(line_index - (second_field ? 10'd284 : 10'd22));
assign canvas_y = picture_de ? {picture_row, field_id} : 9'd0;

// Bresenham-style sample hold: x=floor(sample_in_picture*640/1422).
// No synthesizable divide or frame/line RAM is needed for this aperture.
reg [9:0] logical_x = 10'd0;
reg [10:0] x_remainder = 11'd0;
wire [11:0] x_sum = {1'b0, x_remainder} + 12'd640;
wire [10:0] x_wrapped = 11'(x_sum - PICTURE_SAMPLES);
always @(posedge clk) begin
    if (reset || !active_sample) begin
        logical_x <= 10'd0;
        x_remainder <= 11'd0;
    end else if (x_sum >= PICTURE_SAMPLES) begin
        logical_x <= logical_x + 10'd1;
        x_remainder <= x_wrapped;
    end else begin
        x_remainder <= x_sum[10:0];
    end
end
assign canvas_x = picture_de ? logical_x : 10'd0;
assign pixel_ce = picture_de && (x_remainder < 11'd640);

endmodule
