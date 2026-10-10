// Actual LC scanout with registered palette/VRAM fixtures. Raw V8 signals
// feed the CRT filter in Off mode and portable capture, before any overlays.
module tv_v8_pipeline (
    input wire clk_source, clk_mem, clk_tv, reset_tv, reset_source,
    input wire [3:0] monitor_id,
    input wire source_ce,
    input wire test_pattern,
    input wire actual_memory,
    input wire reset_palette,
    input wire [2:0] video_mode,
    input wire [17:0] cpu_vram_addr,
    input wire [15:0] cpu_vram_data,
    input wire [1:0] cpu_vram_be,
    input wire cpu_vram_we,
    input wire [10:0] cpu_palette_addr,
    input wire [7:0] cpu_palette_data,
    input wire cpu_palette_req, cpu_palette_we, cpu_palette_as_n,
    input wire cpu_palette_uds_n, cpu_palette_lds_n,
    output wire native_de, native_line, native_frame, native_ce,
    output wire [23:0] native_rgb,
    output wire [9:0] native_width,
    output wire [8:0] native_height,
    output wire [28:0] tag_raw, tag_out,
    output wire [23:0] rgb_raw,
    output wire [28:0] address,
    output wire [7:0] burstcount,
    output wire [63:0] writedata,
    output wire [7:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [63:0] readdata,
    output wire [31:0] published, overflows, underruns
);
wire [7:0] palette_addr;
reg [23:0] palette_data;
wire [23:0] actual_palette;
wire [17:0] vram_addr;
wire [15:0] vram_data;
vram_bram framebuffer (
    .a_clk(clk_mem), .a_addr(cpu_vram_addr), .a_din(cpu_vram_data),
    .a_be(cpu_vram_be), .a_we(cpu_vram_we), .a_dout(),
    .b_clk(clk_source), .b_addr(vram_addr), .b_dout(vram_data)
);
ariel_ramdac palette (
    .clk_sys(clk_mem), .clk_pix(clk_source), .reset(reset_palette),
    .reg_addr(cpu_palette_addr), .uds_n(cpu_palette_uds_n), .lds_n(cpu_palette_lds_n),
    .data_in(cpu_palette_data), .data_out(), .we(cpu_palette_we), .req(cpu_palette_req),
    .mem_latch(1'b1), .cpu_as_n(cpu_palette_as_n), .pixel_index(palette_addr),
    .rgb_out(actual_palette), .ariel_written()
);
// Same registered read latency as Ariel. XOR pattern checks all color bits,
// each first/last pixel and row, rather than hiding marker offsets in white.
always @(posedge clk_source)
    palette_data <= {palette_addr, palette_addr ^ 8'h5a, ~palette_addr};
maclc_v8_video source (
    .clk_sys(clk_source), .clk8_en_p(1'b0), .pix_ce(source_ce), .reset(reset_source),
    .video_mode(actual_memory ? video_mode : 3'd3), .monitor_id(monitor_id),
    .test_bypass_vram(test_pattern), .test_pattern_sel(2'd3),
    .hsync(), .vsync(), .hblank(), .vblank(),
    .vga_r(native_rgb[23:16]), .vga_g(native_rgb[15:8]), .vga_b(native_rgb[7:0]),
    .de(native_de), .ce_pix(native_ce),
    .native_line_start(native_line), .native_frame_start(native_frame),
    .native_width(native_width), .native_height(native_height),
    .palette_addr(palette_addr), .palette_data(actual_memory ? actual_palette : palette_data),
    .words_per_line(), .vram_raddr(vram_addr), .vram_rdata(actual_memory ? vram_data : 16'd0)
);
wire filter_de,filter_line,filter_frame,filter_reset;
wire [9:0] filter_width;
wire [8:0] filter_height;
wire [23:0] filter_rgb;
tv_deflicker filter (
    .clk(clk_source), .reset(reset_source), .ce(native_ce), .de(native_de),
    .line_start(native_line), .frame_start(native_frame), .width(native_width),
    .height(native_height), .rgb(native_rgb), .mode(2'd0),
    .out_de(filter_de), .out_line(filter_line), .out_frame(filter_frame),
    .out_width(filter_width), .out_height(filter_height), .out_rgb(filter_rgb), .out_reset(filter_reset)
);
tv_frame_pipeline pipeline (
    .clk_source(clk_source), .source_reset(filter_reset), .source_ce(native_ce), .source_de(filter_de),
    .source_line(filter_line), .source_frame(filter_frame), .source_width(filter_width),
    .source_height(filter_height), .source_rgb(filter_rgb),
    .clk_mem(clk_mem), .inhibit(1'b0), .clk_tv(clk_tv), .reset_tv(reset_tv),
    .a_address(28'd0), .a_burstcount(8'd1), .a_writedata(128'd0), .a_byteenable(16'd0),
    .a_read(1'b0), .a_write(1'b0), .a_waitrequest(), .a_readdatavalid(), .a_readdata(),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest), .readdatavalid(readdatavalid), .readdata(readdata),
    .tag_raw(tag_raw), .tag_out(tag_out), .rgb_raw(rgb_raw), 
    .published(published), .dropped(), .repeated(), .overflows(overflows), .underruns(underruns)
);
endmodule
