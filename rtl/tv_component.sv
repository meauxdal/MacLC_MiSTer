// Three sample-clock stages, matching sys/vga_out.sv's component arithmetic.
// Full-range Y and offset-binary Pb/Pr; physical DAC lanes are {Pr,Y,Pb}.
// This supplies digital codes and aligned sync, NOT analog sync insertion.
module tv_component #(
    parameter integer TAG_WIDTH = 29,
    parameter [TAG_WIDTH-1:0] RESET_TAG = {3'b111, {(TAG_WIDTH-3){1'b0}}}
) (
    input wire clk, reset,
    input wire [23:0] rgb,
    input wire picture_de,
    input wire [TAG_WIDTH-1:0] tag_in,
    output reg [23:0] component,
    output wire [TAG_WIDTH-1:0] tag_out
);
reg signed [18:0] yr, yg, yb, pbr, pbg, pbb, prr, prg, prb;
reg signed [18:0] y_sum, pb_sum, pr_sum;
reg [TAG_WIDTH-1:0] tags [0:2];
assign tag_out = tags[2];
// Widen before arithmetic, so subtraction is signed at every stage.
wire signed [18:0] r = {11'd0, picture_de ? rgb[23:16] : 8'd0};
wire signed [18:0] g = {11'd0, picture_de ? rgb[15:8] : 8'd0};
wire signed [18:0] b = {11'd0, picture_de ? rgb[7:0] : 8'd0};
function automatic [7:0] quantize(input signed [18:0] value);
    if (value < 0) quantize = 8'd0;
    else if (value > 19'sd65535) quantize = 8'd255;
    else quantize = 8'(value >>> 8);
endfunction
always @(posedge clk) begin
    if (reset) begin
        yr <= 0; yg <= 0; yb <= 0;
        pbr <= 19'sd32768; pbg <= 0; pbb <= 0;
        prr <= 19'sd32768; prg <= 0; prb <= 0;
        y_sum <= 0; pb_sum <= 19'sd32768; pr_sum <= 19'sd32768;
        component <= 24'h800080;
        for (integer i=0; i<3; i=i+1) tags[i] <= RESET_TAG;
    end else begin
        yr <= (r<<6)+(r<<3)+(r<<2)+r;
        yg <= (g<<7)+(g<<4)+(g<<2)+(g<<1);
        yb <= (b<<4)+(b<<3)+(b<<2)+b;
        pbr <= 19'sd32768-((r<<5)+(r<<3)+(r<<1));
        pbg <= (g<<6)+(g<<4)+(g<<2)+g;
        pbb <= b<<7;
        prr <= 19'sd32768+(r<<7);
        prg <= (g<<6)+(g<<5)+(g<<3)+(g<<1);
        prb <= (b<<4)+(b<<2)+b;
        y_sum <= yr+yg+yb;
        pb_sum <= pbr-pbg+pbb;
        pr_sum <= prr-prg-prb;
        component <= {quantize(pr_sum),quantize(y_sum),quantize(pb_sum)};
        tags[0] <= tag_in;
        tags[1] <= tags[0];
        tags[2] <= tags[1];
    end
end
endmodule
