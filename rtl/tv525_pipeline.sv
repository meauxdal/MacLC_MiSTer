// Independent 27 MHz TV raster; clocks, reset synchronization and DDR ownership
// belong to the caller. Addresses count 64-bit words; bursts are <=128 beats.
module tv525_pipeline #(
    parameter [27:0] BASE_WORD = 28'h2180000, // 16-byte words; reserve 4 MiB
    parameter FILTER_ENABLE = 0,
    parameter SOURCE_WIDTH = 0, SOURCE_HEIGHT = 0 // zero selects runtime input
) (
    input wire clk_source, source_reset, source_ce, source_de, source_line, source_frame,
    input wire [9:0] source_width,
    input wire [8:0] source_height,
    input wire [23:0] source_rgb,
    input wire [1:0] filter_mode,
    input wire clk_mem, inhibit, clk_tv, reset_tv,
    output wire [23:0] rgb,
    output wire hs, vs, de, field_id, csync_n,
    output wire [28:0] address,
    output wire [7:0] burstcount,
    output wire [63:0] writedata,
    output wire [7:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [63:0] readdata,
    output wire [31:0] published, dropped, repeated, overflows, underruns
);
wire capture_de, capture_line, capture_frame, capture_reset;
wire [9:0] capture_width;
wire [8:0] capture_height;
wire [23:0] capture_rgb;
wire [9:0] input_width=SOURCE_WIDTH!=0 ? 10'(SOURCE_WIDTH) : source_width;
wire [8:0] input_height=SOURCE_HEIGHT!=0 ? 9'(SOURCE_HEIGHT) : source_height;
generate if (FILTER_ENABLE!=0) begin : filtered
    tv_deflicker filter (
        .clk(clk_source), .reset(source_reset), .ce(source_ce), .de(source_de),
        .line_start(source_line), .frame_start(source_frame), .width(input_width),
        .height(input_height), .rgb(source_rgb), .mode(filter_mode),
        .out_de(capture_de), .out_line(capture_line), .out_frame(capture_frame),
        .out_width(capture_width), .out_height(capture_height),
        .out_rgb(capture_rgb), .out_reset(capture_reset)
    );
end else begin : raw
    assign capture_de=source_de, capture_line=source_line, capture_frame=source_frame;
    assign capture_width=input_width, capture_height=input_height;
    assign capture_rgb=source_rgb, capture_reset=source_reset;
    wire unused_mode=^filter_mode;
end endgenerate

wire [27:0] wide_address;
wire [7:0] wide_burstcount;
wire [127:0] wide_writedata, wide_readdata;
wire [15:0] wide_byteenable;
wire wide_read, wide_write, wide_waitrequest, wide_readdatavalid;
tv525_video #(.BASE_WORD(BASE_WORD), .SOURCE_WIDTH(SOURCE_WIDTH), .SOURCE_HEIGHT(SOURCE_HEIGHT)) video (
    .clk_tv(clk_tv), .reset_tv(reset_tv), .clk_mem(clk_mem), .inhibit(inhibit),
    .clk_source(clk_source), .source_reset(capture_reset), .source_ce(source_ce),
    .source_de(capture_de), .source_line(capture_line), .source_frame(capture_frame),
    .source_width(capture_width), .source_height(capture_height), .source_rgb(capture_rgb),
    .rgb(rgb), .hs(hs), .vs(vs), .de(de), .field_id(field_id), .csync_n(csync_n),
    .address(wide_address), .burstcount(wide_burstcount), .writedata(wide_writedata),
    .byteenable(wide_byteenable), .read(wide_read), .write(wide_write),
    .waitrequest(wide_waitrequest), .readdatavalid(wide_readdatavalid), .readdata(wide_readdata),
    .published(published), .dropped(dropped), .repeated(repeated),
    .overflows(overflows), .underruns(underruns)
);
tv_ddram_bridge bridge (
    .clk(clk_mem), .source_address(wide_address), .source_burstcount(wide_burstcount),
    .source_writedata(wide_writedata), .source_byteenable(wide_byteenable),
    .source_read(wide_read), .source_write(wide_write), .source_waitrequest(wide_waitrequest),
    .source_readdatavalid(wide_readdatavalid), .source_readdata(wide_readdata),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest),
    .readdatavalid(readdatavalid), .readdata(readdata)
);
endmodule
