// Standard MiSTer RGB stream. Framework owns OSD, colorspace and board pins.
module tv525_video (
    input wire clk_tv, reset_tv, clk_mem, inhibit,
    input wire clk_source, source_reset, source_ce, source_de, source_line, source_frame,
    input wire [9:0] source_width,
    input wire [8:0] source_height,
    input wire [23:0] source_rgb,
    output wire [23:0] rgb,
    output wire hs, vs, de, field_id,
    output wire [27:0] address,
    output wire [7:0] burstcount,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata
);
wire cs_n, hs_n, vs_n, picture_de, ce, parity, frame_start, field_start, line_start, half_start;
wire [9:0] x, line_number;
wire [8:0] y;
wire [10:0] h_sample;
wire [28:0] tag={cs_n,hs_n,vs_n,picture_de,ce,parity,frame_start,field_start,line_start,half_start,x,y};
wire [28:0] canvas_tag;
wire [23:0] fallback_rgb=24'd0;
tv525_timing timing (
    .clk(clk_tv), .reset(reset_tv), .csync_n(cs_n), .hsync_n(hs_n), .vsync_n(vs_n),
    .picture_de(picture_de), .pixel_ce(ce), .canvas_x(x), .canvas_y(y), .field_id(parity),
    .frame_start(frame_start), .field_start(field_start), .line_start(line_start),
    .halfline_start(half_start), .h_sample(h_sample), .line_number(line_number)
);
tv_buffered_canvas canvas (
    .clk_source(clk_source), .source_reset(source_reset), .source_ce(source_ce),
    .source_de(source_de), .source_line(source_line), .source_frame(source_frame),
    .source_width(source_width), .source_height(source_height), .source_rgb(source_rgb),
    .clk_mem(clk_mem), .inhibit(inhibit), .clk_tv(clk_tv), .reset_tv(reset_tv),
    .tag_in(tag), .h_sample(h_sample), .line_number(line_number), .fallback_rgb(fallback_rgb),
    .tag_out(canvas_tag), .rgb_out(rgb), .address(address), .burstcount(burstcount),
    .writedata(writedata), .byteenable(byteenable), .read(read), .write(write),
    .waitrequest(waitrequest), .readdatavalid(readdatavalid), .readdata(readdata),
    .published(), .dropped(), .repeated(), .overflows(), .underruns()
);
// Sync helpers and parity travel through the same registered lookup as RGB.
assign hs=canvas_tag[27];
assign vs=canvas_tag[26];
assign de=canvas_tag[25];
assign field_id=canvas_tag[23];
wire unused_tag=^{canvas_tag[28],canvas_tag[24],canvas_tag[22:0]};
endmodule
