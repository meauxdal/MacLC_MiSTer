module tv_frame_pipeline (
    input wire clk_source, source_reset, source_ce, source_de, source_line, source_frame,
    input wire [9:0] source_width,
    input wire [8:0] source_height,
    input wire [23:0] source_rgb,
    input wire clk_mem, inhibit, clk_tv, reset_tv,
    input wire [27:0] a_address,
    input wire [7:0] a_burstcount,
    input wire [127:0] a_writedata,
    input wire [15:0] a_byteenable,
    input wire a_read, a_write,
    output wire a_waitrequest, a_readdatavalid,
    output wire [127:0] a_readdata,
    output wire [27:0] address,
    output wire [7:0] burstcount,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata,
    output wire [28:0] tag_raw, tag_out,
    output wire [23:0] rgb_raw, component,
    output wire [31:0] published, dropped, repeated, overflows, underruns
);
wire [27:0] b_address;
wire [7:0] b_burstcount;
wire [127:0] b_writedata, b_readdata;
wire [15:0] b_byteenable;
wire b_read,b_write,b_waitrequest,b_readdatavalid;
tv525_output #(.BUFFERED(1)) video (
    .clk_tv(clk_tv), .reset_tv(reset_tv), .clk_sys(clk_mem), .reset_sys(reset_tv),
    .pattern(3'd0), .geometry(2'd0), .io_osd(1'b0), .io_strobe(1'b0), .io_din(16'd0),
    .av_dis(1'b0), .video_disable(1'b0), .osd_status(), .component(component), .composed_rgb(),
    .tag_raw(tag_raw), .tag_composed(), .tag_out(tag_out), .rgb_raw(rgb_raw),
    .drive_enable(), .dac_r(), .dac_g(), .dac_b(), .low_r(), .low_g(), .low_b(), .hs_n(), .vs_n(),
    .clk_source(clk_source), .source_reset(source_reset), .source_ce(source_ce), .source_de(source_de),
    .source_line(source_line), .source_frame(source_frame), .source_width(source_width),
    .source_height(source_height), .source_rgb(source_rgb), .clk_mem(clk_mem), .inhibit(inhibit),
    .address(b_address), .burstcount(b_burstcount), .writedata(b_writedata), .byteenable(b_byteenable),
    .read(b_read), .write(b_write), .waitrequest(b_waitrequest),
    .readdatavalid(b_readdatavalid), .readdata(b_readdata),
    .published(published), .dropped(dropped), .repeated(repeated), .overflows(overflows), .underruns(underruns)
);
tv_ddr_arbiter arbiter (
    .clk(clk_mem), .inhibit(inhibit),
    .a_address(a_address), .a_burstcount(a_burstcount), .a_writedata(a_writedata), .a_byteenable(a_byteenable),
    .a_read(a_read), .a_write(a_write), .a_waitrequest(a_waitrequest),
    .a_readdatavalid(a_readdatavalid), .a_readdata(a_readdata),
    .b_address(b_address), .b_burstcount(b_burstcount), .b_writedata(b_writedata), .b_byteenable(b_byteenable),
    .b_read(b_read), .b_write(b_write), .b_waitrequest(b_waitrequest),
    .b_readdatavalid(b_readdatavalid), .b_readdata(b_readdata),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest), .readdatavalid(readdatavalid), .readdata(readdata)
);
endmodule
