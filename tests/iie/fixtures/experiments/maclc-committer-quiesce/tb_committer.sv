`timescale 1ns/1ps
module tb_committer;
parameter NEGATIVE_RESET = 0;
parameter BASELINE = 0;
parameter STOP_FINAL_TAIL = 0;
reg clk = 0;
always #5 clk = !clk;
reg rst = 1;
reg sector_valid = 0;
reg upstream_stopped = 0;
wire stopped;
wire [8:0] buf_addr;
reg [7:0] buf_data;
wire [21:0] wr_addr;
wire [15:0] wr_data;
wire wr_req, busy, done;
reg wr_ack = 0;
reg [7:0] bytes [0:511];
reg [15:0] memory [0:255];
integer phase = 0, delay_count = 0, commits = 0, done_count = 0;
integer i, pass;
reg [21:0] saved_addr;
reg [15:0] saved_data;
reg final_tail_seen = 0;

floppy_write_committer dut (
`ifndef BASELINE_SOURCE
    .upstream_stopped(upstream_stopped), .stopped(stopped),
`endif
    .clk(clk), .rst(rst), .sector_valid(sector_valid),
    .sector_addr(22'h1200), .buf_addr(buf_addr), .buf_data(buf_data),
    .wr_addr(wr_addr), .wr_data(wr_data), .wr_req(wr_req), .wr_ack(wr_ack),
    .busy(busy), .done(done), .committed_addr(),
    .sd_buf_addr(), .sd_buf_data(), .sd_buf_wr()
);

always @(posedge clk) buf_data <= bytes[buf_addr];

// Acceptance is delayed; ACK stays high for nine clocks after request low.
always @(posedge clk) begin
    if (done) done_count <= done_count + 1;
    if (!BASELINE && stopped && (busy || done || wr_req || wr_ack || sector_valid))
        $fatal(1, "early stopped");
    case (phase)
    0: if (wr_req) begin
        saved_addr <= wr_addr;
        saved_data <= wr_data;
        delay_count <= 4 + (commits % 5);
        phase <= 1;
    end
    1: begin
        if (!rst && (!wr_req || wr_addr !== saved_addr || wr_data !== saved_data))
            $fatal(1, "offered payload changed");
        if (rst) phase <= 0;
        else if (delay_count != 0) delay_count <= delay_count - 1;
        else begin
            if (saved_addr !== 22'h1200 + commits * 2)
                $fatal(1, "address skipped: commit=%0d addr=%h", commits, saved_addr);
            memory[commits] <= saved_data;
            commits <= commits + 1;
            wr_ack <= 1;
            phase <= 2;
        end
    end
    2: if (!wr_req) begin
        delay_count <= 9;
        phase <= 3;
    end
    3: begin
        if (!BASELINE && wr_req) $fatal(1, "request before ACK low");
        if (commits == 256) final_tail_seen <= 1;
        if (delay_count != 0) delay_count <= delay_count - 1;
        else begin wr_ack <= 0; phase <= 0; end
    end
    endcase
end

initial begin
    for (i = 0; i < 512; i = i + 1) bytes[i] = (i * 37) ^ (i >> 3) ^ 8'hA5;
    repeat (4) @(negedge clk);
    rst = 0;
    @(negedge clk);
    if (!BASELINE && stopped) $fatal(1, "stopped without upstream contract");
    for (pass = 0; pass < (NEGATIVE_RESET || BASELINE ? 1 : 2); pass = pass + 1) begin
        commits = 0;
        done_count = 0;
        final_tail_seen = 0;
        upstream_stopped = 0;
        @(negedge clk); sector_valid = 1;
        @(negedge clk); sector_valid = 0;
        if (STOP_FINAL_TAIL) wait (commits == 256 && phase == 3 && wr_ack);
        else wait (commits == 13);
        @(negedge clk); upstream_stopped = 1;
        if (NEGATIVE_RESET) begin
            rst = 1;
            repeat (3) @(negedge clk);
            rst = 0;
            repeat (40) @(negedge clk);
            if (commits != 13 || busy || wr_req || done_count != 0)
                $fatal(1, "negative control failed");
            $display("PASS immediate_reset discarded sector: commits=13 expected=256 done=0");
            $finish;
        end
        wait (done_count == 1);
        @(negedge clk);
        if (!stopped || commits != 256 || !final_tail_seen)
            $fatal(1, "drain incomplete");
        for (i = 0; i < 256; i = i + 1)
            if (memory[i] !== {bytes[2*i], bytes[2*i+1]})
                $fatal(1, "byte mismatch %0d", i);
        rst = 1;
        @(negedge clk); rst = 0;
        repeat (3) @(negedge clk);
    end
    $display("PASS coordinated commits=256 bytes=512 warm_resets=2 held_ack_clocks=9 stop_final_tail=%0d", STOP_FINAL_TAIL);
    $finish;
end
initial begin #500000; $fatal(1, "watchdog"); end
endmodule
