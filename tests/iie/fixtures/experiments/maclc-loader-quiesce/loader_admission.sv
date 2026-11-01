module loader_admission (
    input wire clk_sys, reset, stop,
    input wire img_mounted, img_readonly,
    input wire [63:0] img_size,
    input wire [23:0] base_addr,
    output wire [31:0] sd_lba,
    output wire sd_rd,
    input wire sd_ack,
    input wire [12:0] sd_buff_addr,
    input wire [15:0] sd_buff_dout,
    input wire sd_buff_wr,
    output wire [23:0] wr_addr,
    output wire [15:0] wr_data,
    output wire wr_req,
    input wire wr_ack,
    output wire loading, done, stopped,
    output wire [63:0] size,
    output wire readonly, raw_img, is_dc42, media_ds,
    output wire [7:0] dc42_fmt,
    input wire [5:0] hdr_addr,
    output wire [15:0] hdr_data,
    output reg pending, overflow,
    output wire admitted
);
    reg [63:0] pending_size;
    reg pending_readonly;
    reg [23:0] pending_base, active_base;
    // A retained mount is deferred work, not an active image operation.
    assign admitted = pending && !stop && !overflow && !loading &&
                      !done && !wr_req && !wr_ack && !sd_rd && !sd_ack;
`ifdef UNSAFE_WORD_IDLE_STOP
    assign stopped = stop && !wr_req && !wr_ack;
`else
    assign stopped = stop && !overflow && !img_mounted && !loading &&
                     !done && !wr_req && !wr_ack && !sd_rd && !sd_ack;
`endif
    always @(posedge clk_sys) begin
        if (reset) begin
            pending <= 0;
            overflow <= 0;
            pending_size <= 0;
            pending_readonly <= 0;
            pending_base <= 0;
            active_base <= 0;
        end else begin
            if (admitted) begin
                pending <= 0;
                active_base <= pending_base;
            end
            if (img_mounted) begin
                if (pending) overflow <= 1;
                else begin
                    pending <= 1;
                    pending_size <= img_size;
                    pending_readonly <= img_readonly;
                    pending_base <= base_addr;
                end
            end
        end
    end
    pinned_floppy_loader engine (
        .clk_sys(clk_sys), .reset(reset),
`ifdef UNSAFE_RAW_MOUNT
        .img_mounted(img_mounted), .img_size(img_size), .img_readonly(img_readonly),
`else
        .img_mounted(admitted), .img_size(pending_size), .img_readonly(pending_readonly),
`endif
`ifdef UNSAFE_LIVE_BASE
        .base_addr(base_addr),
`else
        .base_addr(admitted ? pending_base : active_base),
`endif
        .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_ack(sd_ack),
        .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout), .sd_buff_wr(sd_buff_wr),
        .wr_addr(wr_addr), .wr_data(wr_data), .wr_req(wr_req), .wr_ack(wr_ack),
        .loading(loading), .done(done), .size(size), .readonly(readonly),
        .raw_img(raw_img), .is_dc42(is_dc42), .media_ds(media_ds), .dc42_fmt(dc42_fmt),
        .hdr_addr(hdr_addr), .hdr_data(hdr_data)
    );
endmodule
