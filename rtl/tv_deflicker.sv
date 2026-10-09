// Centered vertical filter on the CRT-only progressive capture stream.
// Every mode delays one row; the last row drains during vertical blanking.
// Two row histories share a synchronous RAM. Read and delayed write addresses
// never collide (supported widths are >=512), so no mixed-port old-data rule
// is needed. Edges replicate the nearest source row; histories never cross
// frames. mode is synchronous to clk and latched on the input frame marker.
module tv_deflicker (
    input wire clk, reset, ce, de, line_start, frame_start,
    input wire [9:0] width,
    input wire [8:0] height,
    input wire [23:0] rgb,
    input wire [1:0] mode, // 0 Off, 1 Mild (1:6:1), 2/3 Strong (1:2:1)
    output reg out_de=0, out_line=0, out_frame=0,
    output reg [23:0] out_rgb=0,
    output reg [9:0] out_width=0,
    output reg [8:0] out_height=0,
    output wire out_reset
);
(* ramstyle="M10K, no_rw_check" *) reg [47:0] rows [0:639];
reg [47:0] row_q;
reg [23:0] below_q=0;
reg [9:0] addr_q=0;
reg write_q=0, pending=0, first_q=0, flush_q=0;
reg line_q=0, frame_q=0;
reg active=0, flushing=0, abort_frame=0;
reg [9:0] x=0, flush_x=0;
reg [8:0] y=0;
reg [1:0] frame_mode=0;
wire geometry_ok=(width==640 && height==480) ||
                 (width==512 && (height==384 || height==342));
wire start=ce && de && frame_start;
wire [9:0] input_x=line_start ? 10'd0 : x;
wire [8:0] input_y=line_start ? y+9'd1 : y;
wire malformed=width!=out_width || height!=out_height ||
               (de && ((line_start && (x!=out_width || input_y>=out_height)) ||
                       (!line_start && x>=out_width))) ||
               (!de && x!=out_width);
// One array reference, one synchronous read port. In Quartus 17 the former
// three procedural reads (including rows[0]) were lowered into asynchronous
// read ports and 30,720 flip-flops despite the ramstyle attribute.
wire [9:0] row_read_addr=start ? 10'd0 : flushing ? flush_x : input_x;
wire row_read=ce && !reset && (start || (flushing && !de) ||
                              (active && de && !malformed));
always @(posedge clk) if (row_read) row_q<=rows[row_read_addr];
// Commit one clock after the read, before this column is visited again.
// Keep both RAM ports separate from reset/control logic for M10K inference.
always @(posedge clk)
    if (write_q && !reset) rows[addr_q]<={below_q,row_q[47:24]};
wire [23:0] center=row_q[47:24];
wire [23:0] above=first_q ? center : row_q[23:0];
wire [23:0] below=flush_q ? center : below_q;
function automatic [7:0] blend(input [7:0] a,c,b, input [1:0] strength);
    begin
        if (strength==0) blend=c;
        else if (strength==1) begin
            blend=8'(({3'd0,a}+({3'd0,c}<<2)+({3'd0,c}<<1)+{3'd0,b}+11'd4)>>3);
        end else begin
            blend=8'(({3'd0,a}+({3'd0,c}<<1)+{3'd0,b}+11'd2)>>2);
        end
    end
endfunction
assign out_reset=reset || abort_frame;
always @(posedge clk) begin
    write_q<=0;
    if (reset) begin
        active<=0; flushing<=0; pending<=0; abort_frame<=0;
        out_de<=0; out_line<=0; out_frame<=0;
    end else if (ce) begin
        abort_frame<=0;
        out_de<=pending; out_line<=pending && line_q; out_frame<=pending && frame_q;
        out_rgb<={blend(above[23:16],center[23:16],below[23:16],frame_mode),
                  blend(above[15:8],center[15:8],below[15:8],frame_mode),
                  blend(above[7:0],center[7:0],below[7:0],frame_mode)};
        pending<=0;
        if (start) begin
            // Abort an unfinished old image before accepting a new one.
            abort_frame<=active || flushing || pending || !geometry_ok || !line_start;
            active<=geometry_ok && line_start; flushing<=0;
            out_width<=width; out_height<=height; frame_mode<=mode;
            x<=1; y<=0;
            addr_q<=0; below_q<=rgb;
            write_q<=geometry_ok && line_start;
        end else if (flushing) begin
            if (de) begin
                abort_frame<=1; flushing<=0; out_de<=0;
            end else begin
                addr_q<=flush_x;
                pending<=1; flush_q<=1; first_q<=0;
                line_q<=flush_x==0; frame_q<=0;
                if (flush_x==out_width-1'b1) flushing<=0;
                else flush_x<=flush_x+1'b1;
            end
        end else if (active) begin
            if (malformed) begin
                abort_frame<=1; active<=0; out_de<=0;
            end else if (de) begin
                addr_q<=input_x; below_q<=rgb; write_q<=1;
                x<=input_x+1'b1; y<=input_y;
                pending<=input_y!=0; first_q<=input_y==1; flush_q<=0;
                line_q<=line_start; frame_q<=line_start && input_y==1;
                if (input_y==out_height-1'b1 && input_x==out_width-1'b1) begin
                    active<=0; flushing<=1; flush_x<=0;
                end
            end
        end
    end
end
endmodule
