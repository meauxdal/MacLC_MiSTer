module tv_deflicker_capture (
    input wire clk, reset, ce, de, line_start, frame_start,
    input wire [9:0] width,
    input wire [8:0] height,
    input wire [23:0] rgb,
    input wire [1:0] mode,
    output wire push, filtered_reset,
    output wire [133:0] data
);
wire fd,fl,ff;
wire [9:0] fw;
wire [8:0] fh;
wire [23:0] frgb;
tv_deflicker filter (
    .clk(clk), .reset(reset), .ce(ce), .de(de), .line_start(line_start),
    .frame_start(frame_start), .width(width), .height(height), .rgb(rgb), .mode(mode),
    .out_de(fd), .out_line(fl), .out_frame(ff), .out_rgb(frgb),
    .out_width(fw), .out_height(fh), .out_reset(filtered_reset)
);
tv_video_capture capture (
    .clk(clk), .reset(filtered_reset), .ce(ce), .de(fd), .line_start(fl),
    .frame_start(ff), .width(fw), .height(fh), .rgb(frgb),
    .full(1'b0), .push(push), .data(data), .overflows()
);
endmodule
