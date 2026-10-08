// TV-coordinate OSD with the sys/osd.v 0x2x/0x4x bitmap/control transport.
// No DE-derived counters, source clock, or alternate-field skipping.
// Bitmap is 256 columns x 128 rows: byte address=(row/8)*256+column,
// bit=row%8. Menu is centered; every bitmap pixel is 2x2 canvas pixels.
// Info positions are bitmap units (also scaled 2x); rectangles clip to canvas.
// Configuration crosses via a held mailbox acknowledged at frame_start.
// Bitmap writes remain live, as in the framework OSD: upload while disabled
// for a static image. Same-address dual-clock read/write is not guaranteed.
module tv_osd #(
    parameter integer TAG_WIDTH = 29,
    parameter [TAG_WIDTH-1:0] RESET_TAG = {3'b111, {(TAG_WIDTH-3){1'b0}}},
    parameter [2:0] OSD_COLOR = 3'd4
) (
    input wire clk_sys, reset_sys,
    input wire io_osd, io_strobe,
    input wire [15:0] io_din,
    output reg osd_status,
    input wire clk_tv, reset_tv, frame_start,
    input wire [9:0] canvas_x,
    input wire [8:0] canvas_y,
    input wire picture_de,
    input wire [23:0] rgb,
    input wire [TAG_WIDTH-1:0] tag_in,
    output reg [23:0] rgb_out,
    output reg [TAG_WIDTH-1:0] tag_out
);
typedef struct packed {
    logic enable_osd, info, highres;
    logic [11:0] x, y;
    logic [8:0] width, height;
    logic [1:0] rotation;
} config_t;
config_t host_config, config_payload, tv_config;
reg request, acknowledge;
(* async_reg = "true" *) reg ack_meta, ack_sync, req_meta, req_sync;
(* ramstyle = "no_rw_check" *) reg [7:0] bitmap [0:4095];
reg old_strobe, has_cmd;
reg [7:0] command;
wire unused_command_bits = ^command[3:1];
wire unused_io_bits = ^io_din[15:12];
reg [12:0] byte_count;
always @(posedge clk_sys) begin
    if (reset_sys) begin
        host_config <= '0; config_payload <= '0; request <= 0;
        ack_meta <= 0; ack_sync <= 0;
        old_strobe <= 0; has_cmd <= 0; command <= 0; byte_count <= 0;
        osd_status <= 0;
    end else begin
        ack_meta <= acknowledge; ack_sync <= ack_meta;
        // Never overwrite a payload until its receiver acknowledges it.
        if (!io_osd && request == ack_sync && host_config != config_payload) begin
            config_payload <= host_config;
            request <= ~request;
        end
        old_strobe <= io_strobe;
        if (!io_osd) begin
            byte_count <= 0; has_cmd <= 0; command <= 0;
            if (command[7:4] == 4) host_config.enable_osd <= command[0];
        end else if (!old_strobe && io_strobe) begin
            if (!has_cmd) begin
                has_cmd <= 1; command <= io_din[7:0];
                if (io_din[7:4] == 4) begin
                    byte_count <= 0;
                    if (!io_din[0]) begin
                        osd_status <= 0; host_config.highres <= 0;
                    end else begin
                        osd_status <= !io_din[2] && !io_din[3];
                        host_config.info <= io_din[2];
                    end
                end
                if (io_din[7:5] == 3'b001) begin
                    if (io_din[3]) host_config.highres <= 1;
                    byte_count <= {io_din[4:0],8'd0};
                end
            end else begin
                if (command[7:4] == 4) begin
                    case (byte_count)
                        0: host_config.x <= io_din[11:0];
                        1: host_config.y <= io_din[11:0];
                        2: host_config.width <= {io_din[5:0],3'd0};
                        3: host_config.height <= {io_din[5:0],3'd0};
                        4: host_config.rotation <= io_din[1:0];
                        default: ;
                    endcase
                end
                if (command[7:5] == 3'b001 && !byte_count[12])
                    bitmap[byte_count[11:0]] <= io_din[7:0];
                byte_count <= byte_count + 13'd1;
            end
        end
    end
end
always @(posedge clk_tv) begin
    if (reset_tv) begin
        req_meta <= 0; req_sync <= 0; acknowledge <= 0; tv_config <= '0;
    end else begin
        req_meta <= request; req_sync <= req_meta;
        if (frame_start && req_sync != acknowledge) begin
            tv_config <= config_payload;
            acknowledge <= req_sync;
        end
    end
end
// Dimensions refer to the bitmap before rotation; cap info dimensions to RAM.
wire [8:0] width = tv_config.info ?
    (tv_config.width > 9'd256 ? 9'd256 : tv_config.width) : 9'd256;
wire [8:0] height = tv_config.info ?
    (tv_config.height > 9'd128 ? 9'd128 : tv_config.height) :
    (tv_config.highres ? 9'd128 : 9'd64);
wire [8:0] display_w = tv_config.rotation[0] ? height : width;
wire [8:0] display_h = tv_config.rotation[0] ? width : height;
wire [12:0] origin_x = tv_config.info ? {tv_config.x,1'b0} :
    (13'd640 - {3'd0,display_w,1'b0}) >> 1;
wire [12:0] origin_y = tv_config.info ? {tv_config.y,1'b0} :
    (13'd480 - {3'd0,display_h,1'b0}) >> 1;
// A rotated 256-high menu exceeds 480 by 32 pixels: clip, without wrapping.
wire [12:0] safe_y = !tv_config.info && display_h > 9'd240 ? 13'd0 : origin_y;
wire [12:0] dx = {3'd0,canvas_x} - origin_x;
wire [12:0] dy = {4'd0,canvas_y} - safe_y;
wire inside_rectangle = picture_de && tv_config.enable_osd &&
    {3'd0,canvas_x} >= origin_x && {4'd0,canvas_y} >= safe_y &&
    dx < {3'd0,display_w,1'b0} && dy < {3'd0,display_h,1'b0};
wire [8:0] u = dx[9:1], v = dy[9:1];
reg [8:0] sx, sy;
always @* begin
    case (tv_config.rotation)
        0: begin sx=u; sy=v; end
        1: begin sx=v; sy=height-9'd1-u; end
        2: begin sx=width-9'd1-u; sy=height-9'd1-v; end
        3: begin sx=width-9'd1-v; sy=u; end
    endcase
end
wire inside_osd = inside_rectangle && sx < width && sy < height;
reg [7:0] osd_byte;
reg [2:0] bit_index;
reg overlay;
reg [23:0] rgb_read;
reg [TAG_WIDTH-1:0] tag_read;
wire pixel = osd_byte[bit_index];
always @(posedge clk_tv) begin
    // Clocked read is intended to infer dual-clock block RAM (32,768 bits).
    osd_byte <= bitmap[{sy[6:3],sx[7:0]}];
    if (reset_tv) begin
        bit_index <= 0; overlay <= 0; rgb_read <= 0; rgb_out <= 0;
        tag_read <= RESET_TAG; tag_out <= RESET_TAG;
    end else begin
        bit_index <= sy[2:0]; overlay <= inside_osd;
        rgb_read <= rgb; tag_read <= tag_in;
        rgb_out <= overlay ?
            {{pixel,pixel,OSD_COLOR[2],rgb_read[23:19]},
             {pixel,pixel,OSD_COLOR[1],rgb_read[15:11]},
             {pixel,pixel,OSD_COLOR[0],rgb_read[7:3]}} : rgb_read;
        tag_out <= tag_read;
    end
end
endmodule
