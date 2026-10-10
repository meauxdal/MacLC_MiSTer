// Portable native stream -> async FIFO -> DDR store -> complete-line RAM.
// Raw raster tags are delayed exactly one TV edge with the synchronous RAM
// pixel lookup. Underflow substitutes an entire black line, never stalls TV.
module tv_buffered_canvas (
    input wire clk_source, source_reset, source_ce, source_de,
    input wire source_line, source_frame,
    input wire [9:0] source_width,
    input wire [8:0] source_height,
    input wire [23:0] source_rgb,
    input wire clk_mem, inhibit,
    input wire clk_tv, reset_tv,
    input wire [28:0] tag_in,
    input wire [10:0] h_sample,
    input wire [9:0] line_number,
    input wire [23:0] fallback_rgb,
    output reg [28:0] tag_out=0,
    output wire [23:0] rgb_out,
    output wire [27:0] address,
    output wire [7:0] burstcount,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata,
    output wire [31:0] published, dropped, repeated, overflows,
    output reg [31:0] underruns=0
);
wire push, full, empty, pop, fifo_valid;
wire [133:0] capture_data, fifo_data;
tv_video_capture capture (
    .clk(clk_source), .reset(source_reset), .ce(source_ce), .de(source_de),
    .line_start(source_line), .frame_start(source_frame),
    .width(source_width), .height(source_height), .rgb(source_rgb),
    .full(full), .push(push), .data(capture_data), .overflows(overflows)
);
// Configuration initialization only. Source reset invalidates capture, never
// resets one half of a FIFO or cancels a DDR command.
tv_capture_fifo #(.WIDTH(134)) capture_fifo (
    .wr_clk(clk_source), .wr_reset(1'b0), .wr_push(push), .wr_data(capture_data), .wr_full(full),
    .rd_clk(clk_mem), .rd_reset(1'b0), .rd_pop(pop), .rd_empty(empty),
    .rd_valid(fifo_valid), .rd_data(fifo_data)
);
reg pair_req=0, line_req=0;
reg [9:0] line_payload=0;
wire pair_ack, line_ack, line_we;
wire [8:0] line_addr;
wire [127:0] line_data;
wire display_valid;
tv_frame_store store (
    .clk(clk_mem), .inhibit(inhibit), .fifo_empty(empty), .fifo_valid(fifo_valid),
    .fifo_data(fifo_data), .fifo_pop(pop), .pair_req(pair_req), .pair_ack(pair_ack),
    .line_req(line_req), .line_payload(line_payload), .line_ack(line_ack),
    .line_we(line_we), .line_addr(line_addr), .line_data(line_data),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest),
    .readdatavalid(readdatavalid), .readdata(readdata),
    .published(published), .dropped(dropped), .repeated(repeated),
    .display_slot(), .display_valid(display_valid)
);
(* ramstyle="M10K, no_rw_check" *) reg [127:0] line_ram [0:511];
always @(posedge clk_mem) if (line_we) line_ram[line_addr]<=line_data;
(* altera_attribute="-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS", preserve, dont_merge *) reg pair_ack_meta=0, pair_ack_sync=0, line_ack_meta=0, line_ack_sync=0;
(* altera_attribute="-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS", preserve, dont_merge *) reg display_meta=0, display_sync=0;
reg have_picture=0, pair_usable=0, line_usable=0;
reg current_bank=0;
reg ack_seen=0;
reg [8:0] ready_row0=0, ready_row1=0;
reg ready0=0, ready1=0;
reg [127:0] pixel_word=0;
reg [1:0] pixel_lane=0;
reg [23:0] fallback_q=0;
reg use_picture_q=0, use_line_q=0;
wire [9:0] x=tag_in[18:9];
// Ask one complete electrical line in advance. Bank alternates per row in
// each field; odd/even canvas rows use the same sequence of banks.
wire next_is_picture=(line_number>=22 && line_number<=261) ||
                     (line_number>=284 && line_number<=523);
wire [8:0] next_y=line_number<=261 ? 9'((line_number-10'd22)*10'd2+10'd1) : 9'((line_number-10'd284)*10'd2);
wire [8:0] current_y=line_number<=262 ? 9'((line_number-10'd23)*10'd2+10'd1) : 9'((line_number-10'd285)*10'd2);
wire next_bank=next_y[1];
wire current_ready=current_y[1] ? ready1 && ready_row1==current_y : ready0 && ready_row0==current_y;
always @(posedge clk_tv) begin
    pair_ack_meta<=pair_ack; pair_ack_sync<=pair_ack_meta;
    line_ack_meta<=line_ack; line_ack_sync<=line_ack_meta;
    display_meta<=display_valid; display_sync<=display_meta;
    tag_out<=tag_in; fallback_q<=fallback_rgb;
    pixel_word<=line_ram[{current_bank,x[9:2]}]; pixel_lane<=x[1:0];
    use_picture_q<=have_picture;
    use_line_q<=line_usable;
    if (reset_tv) begin
        // Never reset mailbox toggles independently of the memory endpoint.
        pair_usable<=0; line_usable<=0; have_picture<=0;
    end else begin
        if (line_ack_sync!=ack_seen) begin
            ack_seen<=line_ack_sync;
            if (line_payload[9]) begin ready_row1<=line_payload[8:0]; ready1<=1; end
            else begin ready_row0<=line_payload[8:0]; ready0<=1; end
        end
        if (tag_in[22] && pair_ack_sync==pair_req) begin
            pair_req<=!pair_req; pair_usable<=0;
            ready0<=0; ready1<=0;
        end
        // One decision before the first request. A late selection blacks
        // this entire pair; it cannot switch descriptors in active video.
        if (tag_in[20] && line_number==21) begin
            pair_usable<=pair_ack_sync==pair_req;
            have_picture<=display_sync;
        end
        if (tag_in[20] && next_is_picture && pair_usable && line_ack_sync==line_req) begin
            line_payload<={next_bank,next_y}; line_req<=!line_req;
            if (next_bank) ready1<=0; else ready0<=0;
        end
        if (h_sample==252) begin
            current_bank<=current_y[1];
            line_usable<=pair_usable && current_ready;
            if (have_picture && ((line_number>=23 && line_number<=262) ||
                                 (line_number>=285 && line_number<=524)) &&
                !(pair_usable && current_ready))
                underruns<=underruns+1'b1;
        end
    end
end
wire [23:0] pixel = pixel_word[pixel_lane*32 +: 24];
assign rgb_out = !tag_out[25] ? 24'd0 : !use_picture_q ? fallback_q :
                 use_line_q ? pixel : 24'd0;
endmodule
