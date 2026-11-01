`timescale 1ns/1ps
module tb_floppy_stop;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, stop_request = 0, req = 0, ready = 0;
    reg rsp_valid = 0, mailbox_drained = 1;
    reg [23:0] addr = 0;
    wire stopped, ack, valid, rsp_ready;
    wire [23:0] frozen_addr;
    integer accepted = 0, responses = 0;
    card_floppy_stop dut (.*);

    always @(posedge clk) begin
        if (!reset && valid && ready) accepted = accepted + 1;
        if (!reset && rsp_valid && rsp_ready) responses = responses + 1;
    end
    initial begin
        #3000;
        $fatal(1, "watchdog");
    end
    task tick;
        begin
            @(posedge clk); #1;
            @(negedge clk);
        end
    endtask
    task check;
        input condition;
        input [511:0] message;
        begin
            if (condition !== 1'b1) $fatal(1, "%0s", message);
        end
    endtask

    initial begin
        tick;
        reset = 0;
        req = 1; addr = 24'h123456;
        tick;
        check(valid && frozen_addr == 24'h123456 && !ack, "offer captured");
        stop_request = 1; addr = 24'hABCDEF; mailbox_drained = 0;
        repeat (4) begin
            tick;
            check(valid && frozen_addr == 24'h123456 && !stopped,
                  "stop retains stalled offer");
        end
        ready = 1;
        tick;
        ready = 0;
        check(!valid && !stopped && accepted == 1, "offer accepted once");
        repeat (3) begin
            tick;
            check(!ack && !rsp_ready && !stopped, "wait outstanding response");
        end
        rsp_valid = 1;
        #1;
        repeat (4) begin
            check(ack && !rsp_ready && !stopped, "REQ holds response ACK during stop");
            tick;
        end
        req = 0;
        #1;
        check(ack && rsp_ready, "REQ low consumes response");
        tick;
        check(!ack && !rsp_ready && !stopped && responses == 1,
              "response consumed once before tail");
        mailbox_drained = 1;
        repeat (3) begin
            tick;
            check(!stopped, "response valid tail blocks stop");
        end
        mailbox_drained = 0; rsp_valid = 0;
        repeat (3) begin
            tick;
            check(!stopped && !ack, "mailbox tail blocks stop after ACK low");
        end
        mailbox_drained = 1;
        tick;
        check(stopped && !ack && !valid, "drained tail stops");
        req = 1; addr = 24'h654321; ready = 1;
        repeat (4) begin
            tick;
            check(stopped && !valid && accepted == 1 && frozen_addr == 24'h123456,
                  "new request blocked while stopped");
        end
        stop_request = 0;
        tick;
        check(valid && frozen_addr == 24'h654321 && !stopped, "resume captures request");
        tick;
        check(!valid && accepted == 2, "resume accepts once");
        ready = 0; mailbox_drained = 0; stop_request = 1; req = 0;
        repeat (3) begin
            tick;
            check(!stopped && !ack && rsp_ready, "released REQ still waits response");
        end
        rsp_valid = 1;
        tick;
        rsp_valid = 0;
        tick;
        check(!stopped && responses == 2, "second response drains exactly once");
        mailbox_drained = 1;
        tick;
        check(stopped && accepted == 2 && responses == 2 && !ack && !valid,
              "second stop fully drained");
        $display("PASS floppy stop: accepted=2 responses=2 stalled-offer held-ACK tail blocked-request resume");
        $finish;
    end
endmodule
