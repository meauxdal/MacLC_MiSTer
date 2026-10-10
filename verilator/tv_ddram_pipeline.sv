module tv_ddram_pipeline (
    input wire clk, inhibit,
    input wire [27:0] source_address,
    input wire [7:0] source_burstcount,
    input wire [127:0] source_writedata,
    input wire [15:0] source_byteenable,
    input wire source_read, source_write,
    output wire source_waitrequest, source_readdatavalid,
    output wire [127:0] source_readdata,
    input wire [28:0] a_address,
    input wire [63:0] a_writedata,
    input wire a_read, a_write,
    output wire a_waitrequest, a_readdatavalid,
    output wire [63:0] a_readdata,
    output wire [28:0] address,
    output wire [7:0] burstcount,
    output wire [63:0] writedata,
    output wire [7:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [63:0] readdata
);
wire [28:0] b_address;
wire [7:0] b_burstcount, b_byteenable;
wire [63:0] b_writedata, b_readdata;
wire b_read, b_write, b_waitrequest, b_readdatavalid;
tv_ddram_bridge bridge (
    .clk(clk), .source_address(source_address), .source_burstcount(source_burstcount),
    .source_writedata(source_writedata), .source_byteenable(source_byteenable),
    .source_read(source_read), .source_write(source_write), .source_waitrequest(source_waitrequest),
    .source_readdatavalid(source_readdatavalid), .source_readdata(source_readdata),
    .address(b_address), .burstcount(b_burstcount), .writedata(b_writedata), .byteenable(b_byteenable),
    .read(b_read), .write(b_write), .waitrequest(b_waitrequest),
    .readdatavalid(b_readdatavalid), .readdata(b_readdata)
);
tv_ddr_arbiter #(.DW(64), .AW(29)) arbiter (
    .clk(clk), .inhibit(inhibit), .a_address(a_address), .a_burstcount(8'd1),
    .a_writedata(a_writedata), .a_byteenable(8'hff), .a_read(a_read), .a_write(a_write),
    .a_waitrequest(a_waitrequest), .a_readdatavalid(a_readdatavalid), .a_readdata(a_readdata),
    .b_address(b_address), .b_burstcount(b_burstcount), .b_writedata(b_writedata),
    .b_byteenable(b_byteenable), .b_read(b_read), .b_write(b_write),
    .b_waitrequest(b_waitrequest), .b_readdatavalid(b_readdatavalid), .b_readdata(b_readdata),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest), .readdatavalid(readdatavalid), .readdata(readdata)
);
endmodule
