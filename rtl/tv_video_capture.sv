// First active pixel carries frame/line markers. Width/height are a coherent
// frame tuple. Emit RGBx quartets and explicit START/END records into FIFO.
// Missing/extra pixels, geometry changes, reset and overflow invalidate the
// whole frame. A later START also abandons an incomplete previous frame.
module tv_video_capture (
    input wire clk, reset, ce, de, line_start, frame_start,
    input wire [9:0] width,
    input wire [8:0] height,
    input wire [23:0] rgb,
    input wire full,
    output wire push,
    output wire [133:0] data,
    output reg [31:0] overflows=0
);
reg active=0, bad=1, old_de=0;
reg [9:0] x=0;
reg [8:0] y=0;
reg [9:0] fw=0;
reg [8:0] fh=0;
reg [1:0] geometry=0;
reg [95:0] packed_pixels=0;
wire [1:0] new_geometry = width==640 ? 2'd2 : height==342 ? 2'd0 : 2'd1;
wire valid_geometry = (width==640 && height==480) ||
                      (width==512 && (height==342 || height==384));
wire start = ce && de && frame_start && !reset;
wire ending = ce && !de && old_de && active && y==fh-1'b1;
wire pixel = ce && de && active && !frame_start && !reset;
wire [1:0] px = line_start ? 2'd0 : x[1:0];
wire quartet = pixel && px==2'd3;
wire [127:0] quartet_data = {8'd0,rgb,packed_pixels[95:0]};
// control,start,end,bad,geometry,pixels
assign push = !reset && (start || ending || quartet) && !full;
assign data = start ? {1'b1,1'b1,1'b0,!valid_geometry,new_geometry,128'd0} :
              ending ? {1'b1,1'b0,1'b1,bad || x!=fw,geometry,128'd0} :
              {1'b0,1'b0,1'b0,bad || width!=fw || height!=fh,geometry,quartet_data};
always @(posedge clk) begin
    if (ce) old_de <= de;
    if (reset) begin active<=0; bad<=1; old_de<=0; x<=0; y<=0; end
    else if (start) begin
        active<=1; bad<=!valid_geometry || full || !line_start;
        fw<=width; fh<=height; geometry<=new_geometry;
        x<=1; y<=0; packed_pixels[31:0]<={8'd0,rgb};
        if (full) overflows<=overflows+1'b1;
    end else if (active) begin
        if (ce && (width!=fw || height!=fh)) bad<=1;
        if (ending) begin active<=0; if (full) overflows<=overflows+1'b1; end
        else if (pixel) begin
            if (line_start) begin
                if (x!=fw || y>=fh-1'b1) bad<=1;
                x<=1; y<=y+1'b1;
            end else begin
                x<=x+1'b1;
                if (x>=fw) bad<=1;
            end
            case (px)
                0: packed_pixels[31:0]<={8'd0,rgb};
                1: packed_pixels[63:32]<={8'd0,rgb};
                2: packed_pixels[95:64]<={8'd0,rgb};
                default: ;
            endcase
            if (quartet && full) begin bad<=1; overflows<=overflows+1'b1; end
        end
    end
end
endmodule
