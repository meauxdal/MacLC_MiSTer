// Two Avalon 128-bit masters; retain ownership through the last write beat
// or read response. Only one read burst is outstanding. No reset may cut a
// presented command: reset inhibits NEW grants; the active grant drains.
module tv_ddr_arbiter (
    input wire clk, inhibit,
    input wire [27:0] a_address, b_address,
    input wire [7:0] a_burstcount, b_burstcount,
    input wire [127:0] a_writedata, b_writedata,
    input wire [15:0] a_byteenable, b_byteenable,
    input wire a_read, a_write, b_read, b_write,
    output wire a_waitrequest, b_waitrequest,
    output wire a_readdatavalid, b_readdatavalid,
    output wire [127:0] a_readdata, b_readdata,
    output wire [27:0] address,
    output wire [7:0] burstcount,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata
);
reg busy = 0, owner = 0, last_owner = 1, reading = 0, command_done = 0;
reg [7:0] remaining = 0;
reg [27:0] command_address=0;
reg [7:0] command_count=0;
reg abort_a=0;
wire selected_write = owner ? b_write : a_write;
wire accepted = (read || write) && !waitrequest;
assign address = command_address;
assign burstcount = command_count;
assign writedata = owner ? b_writedata : a_writedata;
assign byteenable = !owner && (abort_a || inhibit) ? 16'd0 : owner ? b_byteenable : a_byteenable;
assign read = busy && reading && !command_done;
assign write = busy && !reading && (selected_write || (!owner && (abort_a || inhibit)));
assign a_waitrequest = !busy || owner || command_done || waitrequest || abort_a || inhibit;
assign b_waitrequest = !busy || !owner || command_done || waitrequest;
assign a_readdatavalid = busy && reading && !owner && readdatavalid && !abort_a && !inhibit;
assign b_readdatavalid = busy && reading && owner && readdatavalid;
assign a_readdata = readdata;
assign b_readdata = readdata;
always @(posedge clk) begin
    if (!busy) begin
        if (!inhibit && (a_read || a_write || b_read || b_write)) begin
            owner <= (a_read || a_write) && (b_read || b_write) ? !last_owner : (b_read || b_write);
            abort_a<=0;
            if ((a_read || a_write) && (!(b_read || b_write) || last_owner)) begin
                reading <= a_read; remaining <= a_burstcount;
                command_address<=a_address; command_count<=a_burstcount;
            end else begin
                reading <= b_read; remaining <= b_burstcount;
                command_address<=b_address; command_count<=b_burstcount;
            end
            command_done <= 0;
            busy <= 1;
        end
    end else if (reading) begin
        if (accepted) command_done <= 1;
        if (readdatavalid) begin
            remaining <= remaining - 1'b1;
            if (remaining == 1) begin busy <= 0; last_owner <= owner; end
        end
    end else if (accepted) begin
        remaining <= remaining - 1'b1;
        if (remaining == 1) begin busy <= 0; last_owner <= owner; end
    end
    if (busy && !owner && inhibit) abort_a<=1;
end
endmodule
