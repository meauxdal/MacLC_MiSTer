// MiSTer-facing digital wrapper. PLL is instantiated separately by sys_top.
// PLL loss resets BOTH mailbox domains; guest reset is deliberately absent.
module tv525_platform #(
    parameter [2:0] PATTERN = 3'd4,
    parameter [1:0] GEOMETRY = 2'd0,
    parameter BUFFERED=0
) (
    input wire clk_tv, clk_sys, pll_locked,
    input wire io_osd, io_strobe,
    input wire [15:0] io_din,
    input wire av_dis, video_disable,
    output wire osd_status,
    output wire drive_enable,
    output wire [5:0] dac_r, dac_g, dac_b,
    output wire [1:0] low_r, low_g, low_b,
    output wire hs_n, vs_n, csync_n, picture_de,
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
// Asynchronous assertion works even with the PLL stopped. Release takes
// three local edges; both endpoints start from the same reset handshake.
(* async_reg = "true" *) reg [2:0] tv_reset_pipe = 3'b111;
(* async_reg = "true" *) reg [2:0] sys_reset_pipe = 3'b111;
always @(posedge clk_tv or negedge pll_locked)
    if (!pll_locked) tv_reset_pipe <= 3'b111;
    else tv_reset_pipe <= {tv_reset_pipe[1:0],1'b0};
always @(posedge clk_sys or negedge pll_locked)
    if (!pll_locked) sys_reset_pipe <= 3'b111;
    else sys_reset_pipe <= {sys_reset_pipe[1:0],1'b0};
(* async_reg = "true" *) reg disable_meta = 1'b1, disable_sync = 1'b1;
always @(posedge clk_tv) begin
    if (tv_reset_pipe[2]) begin disable_meta <= 1'b1; disable_sync <= 1'b1; end
    else begin disable_meta <= video_disable; disable_sync <= disable_meta; end
end
wire [28:0] tag_stream;
wire [23:0] pin_code;
wire pin_hs, pin_vs;
reg [23:0] pin_code_q = 24'h800080;
reg [28:0] pin_tag_q = {3'b111,26'b0};
reg pin_hs_q = 1'b1, pin_vs_q = 1'b1;
// Keep the output-enable release separate from the high-fanout stream reset.
// It releases on the same third edge as tv_reset_pipe[2], and asynchronously
// clears on lock loss even if clk_tv stops. Prevent synthesis merging it back
// into the reset tree (including the equivalent inverted reset register).
(* preserve, dont_merge *) reg pin_ready = 1'b0;
always @(posedge clk_tv or negedge pll_locked)
    if (!pll_locked) pin_ready <= 1'b0;
    else pin_ready <= !tv_reset_pipe[1];
// Register the complete pin sample after video-disable selection. Color,
// sync and DE all gain one edge together; the raster/OSD pipeline is unchanged.
// The external mux/tri-state remains in sys_top, but no reset or disable mux
// remains between these color registers and that integration boundary.
always @(posedge clk_tv) begin
    if (tv_reset_pipe[2]) begin
        pin_code_q <= 24'h800080;
        pin_tag_q <= {3'b111,26'b0};
        pin_hs_q <= 1'b1;
        pin_vs_q <= 1'b1;
    end else begin
        pin_code_q <= pin_code;
        pin_tag_q <= tag_stream;
        pin_hs_q <= pin_hs;
        pin_vs_q <= pin_vs;
    end
end
wire [28:0] unused_tag_raw, unused_tag_composed;
wire [23:0] unused_rgb_raw, unused_composed_rgb, unused_component;
wire active_drive;
tv525_output #(.BUFFERED(BUFFERED)) stream (
    .clk_tv(clk_tv), .reset_tv(tv_reset_pipe[2]),
    .clk_sys(clk_sys), .reset_sys(sys_reset_pipe[2]),
    .pattern(PATTERN), .geometry(GEOMETRY), .io_osd(io_osd),
    .io_strobe(io_strobe), .io_din(io_din), .osd_status(osd_status),
    .av_dis(av_dis), .video_disable(disable_sync), .drive_enable(active_drive),
    .component(unused_component), .composed_rgb(unused_composed_rgb),
    .tag_raw(unused_tag_raw), .tag_composed(unused_tag_composed),
    .tag_out(tag_stream), .rgb_raw(unused_rgb_raw),
    .dac_r(pin_code[23:18]), .dac_g(pin_code[15:10]), .dac_b(pin_code[7:2]),
    .low_r(pin_code[17:16]), .low_g(pin_code[9:8]), .low_b(pin_code[1:0]),
    .hs_n(pin_hs), .vs_n(pin_vs),
    .clk_source(clk_source), .source_reset(source_reset), .source_ce(source_ce),
    .source_de(source_de), .source_line(source_line), .source_frame(source_frame),
    .source_width(source_width), .source_height(source_height), .source_rgb(source_rgb),
    .clk_mem(clk_mem), .inhibit(inhibit), .address(address), .burstcount(burstcount),
    .writedata(writedata), .byteenable(byteenable), .read(read), .write(write),
    .waitrequest(waitrequest), .readdatavalid(readdatavalid), .readdata(readdata),
    .published(published), .dropped(dropped), .repeated(repeated), .overflows(overflows), .underruns(underruns)
);
// Do not drive the board before TV-clock startup has completed, nor after
// loss of lock. av_dis remains an immediate platform tri-state control.
assign drive_enable = active_drive && pin_ready && pll_locked;
assign {dac_r,low_r} = pin_code_q[23:16];
assign {dac_g,low_g} = pin_code_q[15:8];
assign {dac_b,low_b} = pin_code_q[7:0];
assign hs_n = pin_hs_q;
assign vs_n = pin_vs_q;
assign csync_n = pin_tag_q[28];
assign picture_de = pin_tag_q[25];
wire unused_tag_bits = ^{pin_tag_q[27:26],pin_tag_q[24:0]};
endmodule
