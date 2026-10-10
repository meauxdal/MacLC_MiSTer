// Gray-pointer dual-clock FIFO. RAM read is registered, never combinational
// across clocks. rd_pop returns rd_valid/data one clock later. Both resets
// are configuration/platform resets, NOT guest reset.
module tv_capture_fifo #(parameter WIDTH=133, parameter AW=10) (
    input wire wr_clk, wr_reset, wr_push,
    input wire [WIDTH-1:0] wr_data,
    output wire wr_full,
    input wire rd_clk, rd_reset, rd_pop,
    output wire rd_empty,
    output reg rd_valid,
    output reg [WIDTH-1:0] rd_data
);
(* ramstyle = "M10K, no_rw_check" *) reg [WIDTH-1:0] mem [0:(1<<AW)-1];
reg [AW:0] wr_bin=0, wr_gray=0, rd_bin=0, rd_gray=0;
(* altera_attribute="-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS", preserve, dont_merge *) reg [AW:0] rd_gray_meta=0, rd_gray_sync=0;
(* altera_attribute="-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS", preserve, dont_merge *) reg [AW:0] wr_gray_meta=0, wr_gray_sync=0;
assign wr_full = wr_gray == {~rd_gray_sync[AW:AW-1],rd_gray_sync[AW-2:0]};
assign rd_empty = rd_gray == wr_gray_sync;
wire [AW:0] wr_next = wr_bin + 1'b1, rd_next = rd_bin + 1'b1;
always @(posedge wr_clk) begin
    rd_gray_meta <= rd_gray; rd_gray_sync <= rd_gray_meta;
    if (wr_reset) begin wr_bin<=0; wr_gray<=0; rd_gray_meta<=0; rd_gray_sync<=0; end
    else if (wr_push && !wr_full) begin
        mem[wr_bin[AW-1:0]] <= wr_data;
        wr_bin <= wr_next; wr_gray <= (wr_next>>1)^wr_next;
    end
end
always @(posedge rd_clk) begin
    wr_gray_meta <= wr_gray; wr_gray_sync <= wr_gray_meta;
    rd_valid <= 0;
    if (rd_reset) begin rd_bin<=0; rd_gray<=0; wr_gray_meta<=0; wr_gray_sync<=0; end
    else if (rd_pop && !rd_empty) begin
        rd_data <= mem[rd_bin[AW-1:0]];
        rd_valid <= 1;
        rd_bin <= rd_next; rd_gray <= (rd_next>>1)^rd_next;
    end
end
endmodule
