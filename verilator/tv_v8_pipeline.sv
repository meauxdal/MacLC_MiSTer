// Actual LC scanout with registered palette/VRAM fixtures. Raw V8 signals
// feed exactly the portable capture used by MacLC.sv, before any overlays.
module tv_v8_pipeline (
    input wire clk_source, clk_mem, clk_tv, reset_tv, reset_source,
    input wire [3:0] monitor_id,
    input wire source_ce,
    input wire test_pattern,
    output wire native_de, native_line, native_frame, native_ce,
    output wire [23:0] native_rgb,
    output wire [9:0] native_width,
    output wire [8:0] native_height,
    output wire [28:0] tag_raw, tag_out,
    output wire [23:0] rgb_raw, component,
    output wire [27:0] address,
    output wire [7:0] burstcount,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata,
    output wire [31:0] published, overflows, underruns
);
wire [7:0] palette_addr;
reg [23:0] palette_data;
// Same registered read latency as Ariel. XOR pattern checks all color bits,
// each first/last pixel and row, rather than hiding marker offsets in white.
always @(posedge clk_source)
    palette_data <= {palette_addr, palette_addr ^ 8'h5a, ~palette_addr};
maclc_v8_video source (
    .clk_sys(clk_source), .clk8_en_p(1'b0), .pix_ce(source_ce), .reset(reset_source),
    .video_mode(3'd3), .monitor_id(monitor_id),
    .test_bypass_vram(test_pattern), .test_pattern_sel(2'd3),
    .hsync(), .vsync(), .hblank(), .vblank(),
    .vga_r(native_rgb[23:16]), .vga_g(native_rgb[15:8]), .vga_b(native_rgb[7:0]),
    .de(native_de), .ce_pix(native_ce),
    .native_line_start(native_line), .native_frame_start(native_frame),
    .native_width(native_width), .native_height(native_height),
    .palette_addr(palette_addr), .palette_data(palette_data),
    .words_per_line(), .vram_raddr(), .vram_rdata(16'd0)
);
tv_frame_pipeline pipeline (
    .clk_source(clk_source), .source_reset(reset_source), .source_ce(native_ce), .source_de(native_de),
    .source_line(native_line), .source_frame(native_frame), .source_width(native_width),
    .source_height(native_height), .source_rgb(native_rgb),
    .clk_mem(clk_mem), .inhibit(1'b0), .clk_tv(clk_tv), .reset_tv(reset_tv),
    .a_address(28'd0), .a_burstcount(8'd1), .a_writedata(128'd0), .a_byteenable(16'd0),
    .a_read(1'b0), .a_write(1'b0), .a_waitrequest(), .a_readdatavalid(), .a_readdata(),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest), .readdatavalid(readdatavalid), .readdata(readdata),
    .tag_raw(tag_raw), .tag_out(tag_out), .rgb_raw(rgb_raw), .component(component),
    .published(published), .dropped(), .repeated(), .overflows(overflows), .underruns(underruns)
);
endmodule
