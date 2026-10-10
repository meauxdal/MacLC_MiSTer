`timescale 1ns/1ps
module tb_tv_frame_owner;
reg clk=0; always #5 clk=!clk;
reg inhibit=0,empty=1,valid=0,pair_req=0;
reg [133:0] data=0;
wire pop,pair_ack,write;
wire [27:0] address;
wire [127:0] writedata;
wire [31:0] published,dropped,repeated;
wire [1:0] display_slot;
wire display_valid;
integer ids[0:2];
integer beats=0;
tv_frame_store dut (
    .clk(clk), .inhibit(inhibit), .fifo_empty(empty), .fifo_valid(valid), .fifo_data(data), .fifo_pop(pop),
    .pair_req(pair_req), .pair_ack(pair_ack), .line_req(1'b0), .line_payload(10'd0), .line_ack(),
    .line_we(), .line_addr(), .line_data(), .address(address), .burstcount(), .writedata(writedata),
    .byteenable(), .read(), .write(write), .waitrequest(1'b0), .readdatavalid(1'b0), .readdata(128'd0),
    .published(published), .dropped(dropped), .repeated(repeated), .display_slot(display_slot), .display_valid(display_valid)
);
always @(posedge clk) if(write) begin
    if(display_valid && ((32'(address)-32'h2180000)/76800)==32'(display_slot))
        $fatal(1,"writer owns DISPLAYING memory");
    ids[(address-28'h2180000)/76800]=int'(writedata[31:0]); beats++;
    if(writedata!={4{writedata[31:0]}})$fatal(1,"staged burst data changed");
end
task automatic token(input [133:0] value);
    @(negedge clk);data=value;empty=0;
    while(!pop) @(negedge clk);
    @(negedge clk);valid=1;empty=1;
    @(negedge clk);valid=0;
endtask
task automatic start_frame(input integer id);
    token({1'b1,1'b1,1'b0,1'b0,2'd0,128'(id)});
endtask
task automatic frame(input integer id,input bit bad);
    start_frame(id);
    for(integer i=0;i<43776;i++) token({1'b0,1'b0,1'b0,1'b0,2'd0,{4{32'(id)}}});
    token({1'b1,1'b0,1'b1,bad,2'd0,128'd0});
    repeat(4) @(negedge clk);
endtask
task automatic select_pair(input integer expected);
    @(negedge clk);pair_req=!pair_req;
    while(pair_ack!=pair_req) @(negedge clk);
    if(!display_valid || ids[display_slot]!=expected)
        $fatal(1,"latest-complete/repeat policy: expected %0d got %0d",expected,ids[display_slot]);
endtask
initial begin
    ids[0]=0;ids[1]=0;ids[2]=0;
    frame(1,0);select_pair(1);
    frame(2,0);frame(3,0);select_pair(3); // discard obsolete READY 2
    select_pair(3); // repeat same completed descriptor
    frame(4,1);select_pair(3); // invalid frame never published
    start_frame(5);
    for(integer i=0;i<64;i++)token({6'd0,{4{32'd5}}});
    frame(6,0);select_pair(6); // incomplete frame abandoned at START
    fork
        frame(7,0);
        begin
            wait(write);@(negedge clk);inhibit=1;
            repeat(8) @(negedge clk);inhibit=0;
        end
    join
    select_pair(6); // reset invalidates frame but drains presented burst
    frame(8,0);select_pair(8);
    if(published!=5 || dropped!=4 || repeated!=3)
        $fatal(1,"owner counters published=%0d dropped=%0d repeated=%0d",published,dropped,repeated);
    $display("PASS owner latest READY, complete-pair repeat, invalid/incomplete/reset rejection; beats=%0d published=%0d dropped=%0d repeated=%0d",beats,published,dropped,repeated);
    $finish;
end
endmodule
