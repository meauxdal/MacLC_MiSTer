`timescale 1ns/1ps
module tb_hps_ingress;
reg clk = 0;
always #5 clk = !clk;
reg pll = 0, stop = 0, fenced = 0;
reg io_clk = 0, fp = 0;
reg [15:0] din = 0;
wire io_ack, strobe, download, wr, wait_out;
wire [26:0] byte_addr;
wire [15:0] data;
wire req, slot, local_drained, stopped, fault;
wire [23:0] addr_q;
wire [15:0] data_q;
reg dl_ack = 0;
integer state = 0, delay_count = 0, committed = 0, offers = 0;
integer tail_cycles = 0;
reg [23:0] held_addr;
reg [15:0] held_data;

hps_protocol_source hps(.clk_sys(clk), .io_clk(io_clk),
    .fp_enable(fp), .io_enable(1'b0), .ioctl_wait(wait_out), .io_din(din),
    .io_ack_out(io_ack), .io_strobe_out(strobe), .ioctl_download(download),
    .ioctl_wr(wr), .ioctl_addr(byte_addr), .ioctl_dout(data));
maclc_download dut(.clk_sys(clk), .pll_locked_s(pll), .stop(stop),
    .hps_fenced(fenced), .loader_stopped(1'b1), .committer_stopped(1'b1),
    .ioctl_write(wr), .dio_download(download), .ioctl_data(data),
    .dio_addr(byte_addr[24:1]), .flp_int_wr_req(1'b0),
    .flp_int_wr_addr(24'd0), .flp_int_wr_data(16'd0),
    .wc_req(1'b0), .wc_addr(22'd0), .wc_data(16'd0),
    .dioBusControl(1'b1), .sdram_dl_ack(dl_ack), .ioctl_wait(wait_out),
    .local_drained(local_drained), .stopped(stopped), .protocol_fault(fault),
    .sdram_dlreq_q(req), .sdram_dlslot_q(slot),
    .sdram_dladdr_q(addr_q), .sdram_dldin_q(data_q));

always @(posedge clk) begin
    if (wr) offers = offers + 1;
    if (fault) $fatal(1, "serial HPS overran single-word ingress");
    if (pll) begin
        if (state != 0 && (addr_q !== held_addr || data_q !== held_data))
            $fatal(1, "registered payload changed before ACK tail ended");
        case (state)
            0: if (req) begin
                held_addr = addr_q;
                held_data = data_q;
                if (addr_q !== 24'h500000 + committed)
                    $fatal(1, "ROM address mismatch");
                case (committed)
                    0: if (data_q !== 16'h3412) $fatal(1, "first byte swap");
                    1: if (data_q !== 16'hcdab) $fatal(1, "second byte swap");
                    2: if (data_q !== 16'haa55) $fatal(1, "third byte swap");
                    default: $fatal(1, "duplicate ROM request");
                endcase
                delay_count = 5;
                state = 1;
            end
            1: begin
                if (!req) $fatal(1, "request dropped before acceptance");
                if (delay_count == 0) begin
                    dl_ack <= 1;
                    committed = committed + 1;
                    state = 2;
                end else delay_count = delay_count - 1;
            end
            2: if (!req) begin delay_count = 9; state = 3; end
            3: begin
                if (req) $fatal(1, "request repeated during held ACK");
                if (local_drained) $fatal(1, "drain ignored held ACK");
                tail_cycles = tail_cycles + 1;
                if (delay_count == 0) begin dl_ack <= 0; state = 0; end
                else delay_count = delay_count - 1;
            end
        endcase
    end
end

task tick;
    begin @(posedge clk); #1; end
endtask
task finish_word;
    begin
        while (io_ack !== 1) tick;
        @(negedge clk); io_clk = 0;
        while (io_ack !== 0) tick;
    end
endtask
task send_word(input [15:0] value);
    begin
        @(negedge clk); fp = 1; din = value; io_clk = 1;
        finish_word;
    end
endtask
task end_frame;
    begin @(negedge clk); fp = 0; tick; end
endtask

initial begin #30000; $fatal(1, "watchdog"); end
initial begin
    repeat (4) tick;
    @(negedge clk); pll = 1;
    repeat (2) tick;
    send_word(16'h0053);
    send_word(16'h0001);
    end_frame;
    if (download !== 1) $fatal(1, "download did not start");
    send_word(16'h0054);
    send_word(16'h1234);

    // Stop and the real HPS data strobe share an edge; retain the offered word.
    @(negedge clk); fp = 1; din = 16'habcd; io_clk = 1; stop = 1;
    while (committed != 2 || !local_drained) tick;
    repeat (3) tick;
    if (offers != 2 || io_ack !== 0 || fault || stopped)
        $fatal(1, "stop-coincident word or blocked host ACK mismatch");
    if (committed != 2 || !download || !wait_out)
        $fatal(1, "stop discarded active session");
    @(negedge clk); fenced = 1;
    tick;
    if (stopped) $fatal(1, "active download falsely reported stopped");
    @(negedge clk); fenced = 0; stop = 0;
    finish_word;
    send_word(16'h55aa);
    end_frame;
    send_word(16'h0053);
    send_word(16'h0000);
    end_frame;
    while (!local_drained) tick;
    if (offers != 3 || committed != 3 || tail_cycles != 30 || download || fault)
        $fatal(1, "finite ROM accounting or final session mismatch");
    @(negedge clk); stop = 1;
    tick;
    if (stopped) $fatal(1, "missing HPS fence accepted");
    @(negedge clk); fenced = 1;
    tick;
    if (!stopped) $fatal(1, "fenced drained endpoint did not stop");
    $display("PASS HPS ingress composition: offers=3 commits=3 held_tail=30 stop_word=1 resume=1");
    $finish;
end
endmodule
