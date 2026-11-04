`timescale 1ns/1ps
module tb_slot_host;
    reg clk = 0, reset = 1, phase = 0;
    always #5 clk = !clk;
    always @(posedge clk) phase <= !phase;
    wire [31:0] address;
    wire [15:0] data_out, data_in;
    wire rw_n, as_n, uds_n, lds_n;
    reg [15:0] memory [0:131071];
    reg active = 0;
    integer table_reads = 0, replies = 0, ack_reads = 0, acks = 0;
    wire [31:0] bus_address = {address[31:1], 1'b0};
    wire table_read = !as_n && rw_n && bus_address == 32'h00003018 && !lds_n;
    assign data_in = memory[address[17:1]];

    tg68k host (
        .clk(clk), .reset(reset), .phi1(phase), .phi2(!phase), .cpu(2'b11),
        .dtack_n(1'b0), .rw_n(rw_n), .as_n(as_n), .uds_n(uds_n), .lds_n(lds_n),
        .fc(), .reset_n(), .E(), .E_div(1'b1), .E_PosClkEn(), .E_NegClkEn(),
        .vma_n(), .vpa_n(1'b1), .br_n(1'b1), .bg_n(), .bgack_n(1'b1), .ipl(3'b111),
        .berr(1'b0), .din(data_in), .dout(data_out), .longword(), .addr(address),
        .addr_early(), .busstate()
    );

    always @(posedge clk) begin
        if (as_n) active <= 0;
        if (!reset && !as_n && !active && (!uds_n || !lds_n)) begin
            active <= 1;
            if (table_read) table_reads <= table_reads + 1;
            if (rw_n && bus_address == 32'h0000400C) ack_reads <= ack_reads + 1;
            if (!rw_n) begin
                if (bus_address == 32'h0000400C) begin
                    if (address[0] || uds_n || !lds_n || data_out[15:8] !== 8'h00)
                        $fatal(1, "original host write mismatch address=%h data=%h", address, data_out);
                    acks <= acks + 1;
                end
                if (bus_address == 32'h00004018 && !lds_n) begin
                    if (!uds_n || data_out[7:0] !== 8'h5A)
                        $fatal(1, "original read reply mismatch got=%h", data_out[7:0]);
                    replies <= replies + 1;
                end
                if (bus_address < 32'h00040000) begin
                    if (!uds_n) memory[address[17:1]][15:8] <= data_out[15:8];
                    if (!lds_n) memory[address[17:1]][7:0] <= data_out[7:0];
                end
            end
        end
        if (!reset && !as_n && !rw_n && bus_address == 32'h00009000) begin
            if (table_reads != 1 || replies != 1 || ack_reads != 1 || acks != 1 || memory[17'h0200C][7:0] != 8'h5A)
                $fatal(1, "host completion mismatch reads=%0d replies=%0d ack_reads=%0d acks=%0d", table_reads, replies, ack_reads, acks);
            $display("PASS original CNmc TG68K read +19 reply and write +0C ACK; synthetic endpoint only");
            $finish;
        end
    end

    initial begin
        reg [4095:0] path;
        if (!$value$plusargs("image=%s", path)) $fatal(1, "missing image");
        $readmemh(path, memory);
        repeat (8) @(negedge clk);
        reset = 0;
    end
    initial begin
        #200000;
        $fatal(1, "host routine timeout address=%h replies=%0d acks=%0d", address, replies, acks);
    end
endmodule
