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
wire [28:0] tag_out;
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
    .tag_out(tag_out), .rgb_raw(unused_rgb_raw),
    .dac_r(dac_r), .dac_g(dac_g), .dac_b(dac_b),
    .low_r(low_r), .low_g(low_g), .low_b(low_b), .hs_n(hs_n), .vs_n(vs_n),
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
assign drive_enable = active_drive && !tv_reset_pipe[2] && pll_locked;
assign csync_n = tag_out[28];
assign picture_de = tag_out[25];
wire unused_tag_bits = ^{tag_out[27:26],tag_out[24:0]};
endmodule
