`timescale 1ns/1ps
module tb_host_stop;
parameter STOP_STATE = -1;
parameter USE_VPA = 0;
parameter ENABLE = 1;
parameter HOLD_ACK = 0;
parameter INJECT_BERR = 0;
parameter CPU = 3;
reg clk = 0;
always #5 clk = !clk;
reg reset = 1, stop_req = 0;
wire stopped, rw_n, as_n, uds_n, lds_n;
wire [31:0] addr;
wire [15:0] dout;
reg [15:0] mem [0:2047];
wire [15:0] din = mem[addr[11:1]];
reg [3:0] delay_count = 0;
reg [1:0] phase = 0;
reg [3:0] ack_tail = 0;
reg prev_as = 1;
wire dtack_n = (as_n || delay_count < 7 || USE_VPA) && ack_tail == 0;
wire vpa_n = !(USE_VPA && !as_n);
reg berr_seen = 0;
reg berr_sampled = 0;
wire berr = INJECT_BERR && !berr_seen && !as_n && addr == 32'h400 && rw_n;
integer ticks = 0, last_enable = -100, writes = 0, pauses = 0;
integer i;
string dump_path;
reg served = 0;
reg [31:0] held_addr;
reg [15:0] held_data;
reg [2:0] held_bus;
reg cycle_active = 0;
reg [31:0] cycle_addr;
reg [15:0] cycle_data;
reg [2:0] cycle_bus;
tg68k #(.QUIESCE(ENABLE)) dut (
    .clk(clk), .reset(reset), .stop_req(stop_req), .stopped(stopped),
    .phi1(phase == 0), .phi2(phase == 2), .cpu(CPU[1:0]),
    .dtack_n(dtack_n), .rw_n(rw_n), .as_n(as_n), .uds_n(uds_n),
    .lds_n(lds_n), .addr(addr), .din(din), .dout(dout),
    .E_div(1'b0), .vpa_n(vpa_n), .br_n(1'b1), .bgack_n(1'b1),
    .ipl(3'b111), .berr(berr)
);
always @(posedge clk) begin
    ticks = ticks + 1;
    phase <= phase + 1'b1;
    prev_as <= as_n;
    if (berr) berr_seen <= 1;
    if (dut.s_state == 4 && dut.berr_held) berr_sampled <= 1;
    if (!prev_as && as_n && HOLD_ACK && stop_req) ack_tail <= 7;
    else if (ack_tail != 0) ack_tail <= ack_tail - 1'b1;
    if (ticks > 10000) $fatal(1, "watchdog addr=%h state=%d writes=%d", addr, dut.s_state, writes);
    if (!reset && dut.tg68_clkena) begin
        if (ticks - last_enable < 2) $fatal(1, "enable spacing");
        last_enable = ticks;
    end
    if (as_n) begin
        delay_count <= 0;
        served <= 0;
    end else begin
        if (delay_count < 15) delay_count <= delay_count + 1'b1;
        if (!served && dut.s_state == 2) begin
            if (!rw_n) begin
                if (!uds_n) mem[addr[11:1]][15:8] <= dout[15:8];
                if (!lds_n) mem[addr[11:1]][7:0] <= dout[7:0];
                writes = writes + 1;
            end
            served <= 1;
        end
    end
end
always @(negedge clk) begin
    if (!reset && !as_n) begin
        if (cycle_active && (addr !== cycle_addr || dout !== cycle_data ||
            {rw_n, uds_n, lds_n} !== cycle_bus)) $fatal(1, "accepted payload changed");
        cycle_active = 1;
        cycle_addr = addr;
        cycle_data = dout;
        cycle_bus = {rw_n, uds_n, lds_n};
    end else cycle_active = 0;
end
task pause_once;
    begin
        stop_req = 1;
        wait(stopped);
        @(negedge clk);
        if (!as_n || !uds_n || !lds_n || !dtack_n || !dut.vma_n ||
            dut.berr_held || dut.s_state != 0 || dut.tg68_clkena)
            $fatal(1, "premature stopped");
        held_addr = addr;
        held_data = dout;
        held_bus = {rw_n, uds_n, lds_n};
        repeat (12) begin
            @(negedge clk);
            if (!stopped || !as_n || dut.tg68_clkena || addr !== held_addr ||
                dout !== held_data || {rw_n, uds_n, lds_n} !== held_bus)
                $fatal(1, "paused payload changed");
        end
        pauses = pauses + 1;
        stop_req = 0;
    end
endtask
initial begin
    for (i = 0; i < 2048; i = i + 1) mem[i] = 16'h4e71;
    mem[0] = 0; mem[1] = 16'h0f00;
    mem[2] = 0; mem[3] = 16'h0100;
    mem[4] = 0; mem[5] = 16'h0180;
    // MOVE.L #$12345678,$400; MOVE.L $400,D0; ADDQ.L #1,$400;
    // TAS $404; MOVE.W #$55aa,$406; BRA.S .
    mem[128] = 16'h23fc; mem[129] = 16'h1234; mem[130] = 16'h5678;
    mem[131] = 0; mem[132] = 16'h0400;
    mem[133] = 16'h2039; mem[134] = 0; mem[135] = 16'h0400;
    mem[136] = 16'h52b9; mem[137] = 0; mem[138] = 16'h0400;
    mem[139] = 16'h4af9; mem[140] = 0; mem[141] = 16'h0404;
    mem[142] = 16'h33fc; mem[143] = 16'h55aa;
    mem[144] = 0; mem[145] = 16'h0406; mem[146] = 16'h60fe;
    // Bus-error handler writes the same marker, then parks.
    mem[192] = 16'h33fc; mem[193] = 16'h55aa;
    mem[194] = 0; mem[195] = 16'h0406; mem[196] = 16'h60fe;
    mem[512] = 0; mem[513] = 0; mem[514] = 0; mem[515] = 0;
    repeat (10) @(negedge clk);
    reset = 0;
    if (!ENABLE) stop_req = 1;
    if (STOP_STATE == 5 && ENABLE) begin
        wait(dut.s_state == 0 && dut.tg68_busstate == 1);
        @(negedge clk);
        pause_once();
    end else if (STOP_STATE >= 0 && ENABLE) begin
        // Stop separately on each longword lane and the TAS read/write.
        for (i = 0; i < (INJECT_BERR ? 3 : 10); i = i + 1) begin
            wait(!as_n && addr >= 32'h400 && addr <= 32'h404);
            wait(dut.s_state == STOP_STATE);
            @(negedge clk);
            pause_once();
            wait(as_n);
            @(negedge clk);
        end
    end
    wait(mem[515] == 16'h55aa);
    repeat (15) @(negedge clk);
    if (mem[512] !== 16'h1234 || mem[513] !== 16'h5679 || mem[514] !== 16'h8000)
        $fatal(1, "program result %h %h %h", mem[512], mem[513], mem[514]);
    if (INJECT_BERR && (!berr_seen || !berr_sampled)) $fatal(1, "BERR not retained to kernel enable");
    if (!$value$plusargs("dump=%s", dump_path)) $fatal(1, "missing memory dump path");
    $writememh(dump_path, mem);
    $display("PASS host-stop cpu=%0d state=%0d vpa=%0d enable=%0d held_ack=%0d berr=%0d pauses=%0d writes=%0d ticks=%0d", CPU, STOP_STATE, USE_VPA, ENABLE, HOLD_ACK, INJECT_BERR, pauses, writes, ticks);
    $finish;
end
endmodule
