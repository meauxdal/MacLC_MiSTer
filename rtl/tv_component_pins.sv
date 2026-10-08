// Digital lane adapter only. Platform must apply drive_enable as tri-state
// at top-level pins, preserve SD sharing, and implement the board's sync-on-Y.
module tv_component_pins (
    input wire [23:0] component,
    input wire csync_n,
    input wire av_dis, video_disable,
    output wire drive_enable,
    output wire [5:0] dac_r, dac_g, dac_b,
    output wire [1:0] low_r, low_g, low_b,
    output wire hs_n, vs_n
);
wire [23:0] code = video_disable ? 24'h800080 : component;
assign drive_enable = !av_dis;
assign {dac_r,low_r} = code[23:16];
assign {dac_g,low_g} = code[15:8];
assign {dac_b,low_b} = code[7:0];
assign hs_n = video_disable || csync_n;
assign vs_n = 1'b1; // composite sync on HS; no rectangular VS reconstruction
endmodule
