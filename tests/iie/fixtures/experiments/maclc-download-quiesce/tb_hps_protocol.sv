`timescale 1ns/1ps
module tb_hps_protocol #(parameter DROP_ON_STOP = 0);
reg clk = 0;
always #5 clk = !clk;
reg io_clk = 0, fp = 0, wait_in = 0, stop = 0;
reg [15:0] din = 0;
wire ack, strobe, download, wr;
wire [26:0] addr;
wire [15:0] data;
integer captured = 0, writes_at_stop = 0;
reg [26:0] captured_addr [0:3];
reg [15:0] captured_data [0:3];
hps_protocol_source dut(.clk_sys(clk), .io_clk(io_clk),
    .fp_enable(fp), .io_enable(1'b0), .ioctl_wait(wait_in), .io_din(din),
    .io_ack_out(ack), .io_strobe_out(strobe), .ioctl_download(download),
    .ioctl_wr(wr), .ioctl_addr(addr), .ioctl_dout(data));

always @(posedge clk) if (wr && !(DROP_ON_STOP && stop)) begin
    if (captured >= 4) $fatal(1, "capture overflow");
    captured_addr[captured] = addr;
    captured_data[captured] = data;
    captured = captured + 1;
    if (stop) writes_at_stop = writes_at_stop + 1;
end

task tick;
    begin @(posedge clk); #1; end
endtask
task send_word(input [15:0] value);
    begin
        @(negedge clk); fp = 1; din = value; io_clk = 1;
        while (ack !== 1) tick;
        @(negedge clk); io_clk = 0;
        while (ack !== 0) tick;
    end
endtask
task end_frame;
    begin @(negedge clk); fp = 0; tick; end
endtask

initial begin
    #10000; $fatal(1, "watchdog");
end

initial begin
    repeat (4) tick;
    // Wait does not suppress the next rising strobe, only its ACK completion.
    @(negedge clk); wait_in = 1; fp = 1; io_clk = 1; din = 16'h0053;
    tick;
    if (dut.fio_block.cmd !== 16'h0053 || dut.fio_block.has_cmd !== 1)
        $fatal(1, "preasserted wait blocked command strobe unexpectedly");
    repeat (3) tick;
    if (ack !== 0) $fatal(1, "wait did not hold ACK");
    @(negedge clk); wait_in = 0;
    while (ack !== 1) tick;
    @(negedge clk); io_clk = 0;
    while (ack !== 0) tick;
    send_word(16'h0001);
    // The already captured start commits on frame close with wait still HIGH.
    @(negedge clk); wait_in = 1; stop = 1; fp = 0;
    tick;
    if (download !== 1) $fatal(1, "expected start despite preasserted wait");
    $display("PROVED wait=1 does not reserve session admission; frame close starts download");

    @(negedge clk); wait_in = 0; stop = 0;
    send_word(16'h0054);
    // A data strobe and stop can coincide; wr traverses its real two-edge tail.
    @(negedge clk); din = 16'h1234; io_clk = 1; wait_in = 1; stop = 1;
    tick;
    if (data !== 16'h1234 || wr !== 0 || captured != 0)
        $fatal(1, "unexpected initial data pipeline");
    tick;
    if (wr !== 1 || captured != 0) $fatal(1, "missing registered write pulse");
    tick;
    if (captured != 1 || writes_at_stop != 1 || captured_addr[0] !== 0 ||
        captured_data[0] !== 16'h1234) $fatal(1, "stop lost offered word");
    repeat (3) tick;
    if (captured != 1 || data !== 16'h1234 || addr !== 0 || ack !== 0)
        $fatal(1, "stalled payload changed or repeated");

    @(negedge clk); wait_in = 0; stop = 0;
    while (ack !== 1) tick;
    @(negedge clk); io_clk = 0;
    while (ack !== 0) tick;
    send_word(16'habcd);
    repeat (3) tick;
    if (captured != 2 || captured_addr[1] !== 2 || captured_data[1] !== 16'habcd)
        $fatal(1, "resume address or payload mismatch");
    end_frame;
    send_word(16'h0053);
    send_word(16'h0000);
    end_frame;
    if (download !== 0) $fatal(1, "stop frame failed");
    if (captured != 2) $fatal(1, "unexpected extra write");
    $display("PASS HPS framing: 2 words captured once; stop-coincident word retained; resume at byte 2");
    $finish;
end
endmodule
