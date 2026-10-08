// Diagnostic or buffered native canvas -> TV OSD -> component -> pin adapter.
// BUFFERED=0 retains the CRT-qualified diagnostic stream and its latency.
// Resets must be asserted together and released synchronously in each domain.
module tv525_output #(parameter BUFFERED=0) (
    input wire clk_tv, reset_tv, clk_sys, reset_sys,
    input wire [2:0] pattern,
    input wire [1:0] geometry,
    input wire io_osd, io_strobe,
    input wire [15:0] io_din,
    input wire av_dis, video_disable,
    output wire osd_status,
    output wire [23:0] component, composed_rgb,
    output wire [28:0] tag_raw, tag_composed, tag_out,
    output wire [23:0] rgb_raw,
    output wire drive_enable,
    output wire [5:0] dac_r, dac_g, dac_b,
    output wire [1:0] low_r, low_g, low_b,
    output wire hs_n, vs_n,
    input wire clk_source, source_reset, source_ce, source_de, source_line, source_frame,
    input wire [9:0] source_width,
    input wire [8:0] source_height,
    input wire [23:0] source_rgb,
    input wire clk_mem, inhibit,
    output wire [27:0] address,
    output wire [7:0] burstcount,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata,
    output wire [31:0] published, dropped, repeated, overflows, underruns
);
wire cs, hs, vs, de, ce, field_id, frame, field_start, line_start, half_start;
wire [9:0] x;
wire [8:0] y;
wire [10:0] unused_h_sample;
wire [9:0] unused_line_number;
wire unused_image_de;
wire [23:0] diagnostic_rgb;
wire [23:0] canvas_rgb;
wire [28:0] canvas_tag;
tv525_timing timing (
    .clk(clk_tv), .reset(reset_tv), .csync_n(cs), .hsync_n(hs), .vsync_n(vs),
    .picture_de(de), .pixel_ce(ce), .canvas_x(x), .canvas_y(y),
    .field_id(field_id), .frame_start(frame), .field_start(field_start),
    .line_start(line_start), .halfline_start(half_start),
    .h_sample(unused_h_sample), .line_number(unused_line_number)
);
// Keep diagnostic controls steady for each pair. Future platform controls
// require a separate coherent frame-boundary mailbox, as the OSD does.
tv_test_pattern picture (
    .picture_de(de), .canvas_x(x), .canvas_y(y), .field_id(field_id),
    .pattern(pattern), .geometry(geometry), .rgb(diagnostic_rgb), .image_de(unused_image_de)
);
// 28:26 sync; 25 DE; 24 CE; 23 parity; 22 frame; 21 field;
// 20 line; 19 half-line; 18:9 x; 8:0 y. One tag travels with every sample.
assign tag_raw = {cs,hs,vs,de,ce,field_id,frame,field_start,line_start,half_start,x,y};
generate if (BUFFERED != 0) begin : buffered
    tv_buffered_canvas canvas (
        .clk_source(clk_source), .source_reset(source_reset), .source_ce(source_ce),
        .source_de(source_de), .source_line(source_line), .source_frame(source_frame),
        .source_width(source_width), .source_height(source_height), .source_rgb(source_rgb),
        .clk_mem(clk_mem), .inhibit(inhibit), .clk_tv(clk_tv), .reset_tv(reset_tv),
        .tag_in(tag_raw), .h_sample(unused_h_sample), .line_number(unused_line_number),
        .fallback_rgb(diagnostic_rgb), .tag_out(canvas_tag), .rgb_out(canvas_rgb),
        .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
        .read(read), .write(write), .waitrequest(waitrequest),
        .readdatavalid(readdatavalid), .readdata(readdata),
        .published(published), .dropped(dropped), .repeated(repeated), .overflows(overflows), .underruns(underruns)
    );
end else begin : diagnostic
    assign canvas_tag=tag_raw;
    assign canvas_rgb=diagnostic_rgb;
    assign address=0; assign burstcount=1; assign writedata=0; assign byteenable=0;
    assign read=0; assign write=0;
    assign published=0; assign dropped=0; assign repeated=0; assign overflows=0; assign underruns=0;
    wire unused_inputs=^{clk_source,source_reset,source_ce,source_de,source_line,source_frame,
                        source_width,source_height,source_rgb,clk_mem,inhibit,waitrequest,readdatavalid,readdata};
end endgenerate
assign rgb_raw=canvas_rgb;
tv_osd osd (
    .clk_sys(clk_sys), .reset_sys(reset_sys), .io_osd(io_osd),
    .io_strobe(io_strobe), .io_din(io_din), .osd_status(osd_status),
    .clk_tv(clk_tv), .reset_tv(reset_tv), .frame_start(canvas_tag[22]),
    .canvas_x(canvas_tag[18:9]), .canvas_y(canvas_tag[8:0]), .picture_de(canvas_tag[25]), .rgb(canvas_rgb),
    .tag_in(canvas_tag), .rgb_out(composed_rgb), .tag_out(tag_composed)
);
tv_component converter (
    .clk(clk_tv), .reset(reset_tv), .rgb(composed_rgb),
    .picture_de(tag_composed[25]), .tag_in(tag_composed),
    .component(component), .tag_out(tag_out)
);
tv_component_pins pins (
    .component(component), .csync_n(tag_out[28]), .av_dis(av_dis),
    .video_disable(video_disable), .drive_enable(drive_enable),
    .dac_r(dac_r), .dac_g(dac_g), .dac_b(dac_b),
    .low_r(low_r), .low_g(low_g), .low_b(low_b), .hs_n(hs_n), .vs_n(vs_n)
);
endmodule
