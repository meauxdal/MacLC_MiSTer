`timescale 1ns/1ps
module tb_launch_bus;
    reg clk = 0, reset = 1, phase = 0;
    always #7.69225 clk = !clk;
    always @(posedge clk) phase <= !phase;
    wire [31:0] address;
    wire [15:0] data_out, data_in, card_data;
    wire rw_n, as_n, uds_n, lds_n;
    wire [2:0] fc;
    wire claim, dtack_n, error, fault, boundary;
    wire [15:0] card_cpu, instruction_address, capture_address;
    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [31:0] captures, completed;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_data;
    reg mem_rsp_valid = 0;
    wire [31:0] bus_address = {address[31:1], 1'b0};
    wire [31:0] mapped = bus_address[31:24] == 8'hFE ? {8'h80, bus_address[23:0]} : bus_address;
    wire cpu_dtack = claim ? (error ? 1'b1 : dtack_n) : 1'b0;
    reg [15:0] rom [0:255];
    assign data_in = claim ? card_data : rom[address[8:1]];
    tg68k host (
        .clk(clk), .reset(reset), .phi1(phase), .phi2(!phase), .cpu(2'b11),
        .dtack_n(cpu_dtack), .rw_n(rw_n), .as_n(as_n), .uds_n(uds_n), .lds_n(lds_n),
        .fc(fc), .reset_n(), .E(), .E_div(1'b1), .E_PosClkEn(), .E_NegClkEn(),
        .vma_n(), .vpa_n(1'b1), .br_n(1'b1), .bg_n(), .bgack_n(1'b1), .ipl(3'b111),
        .berr(1'b0), .din(data_in), .dout(data_out), .longword(), .addr(address),
        .addr_early(), .busstate()
    );
    card_irq_pds_candidate card (
        .clk(clk), .por_n(!reset), .host_reset(reset), .pds_address(mapped), .pds_fc(fc),
        .pds_as_n(as_n), .pds_uds_n(uds_n), .pds_lds_n(lds_n), .pds_rw(rw_n),
        .pds_write_data(data_out), .claim(claim), .dtack_n(dtack_n), .pds_read_data(card_data),
        .error(error), .mem_valid(mem_valid), .mem_ready(!mem_rsp_valid), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_data), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(16'b0), .fault(fault), .boundary(boundary),
        .card_cpu_address(card_cpu), .instruction_address(instruction_address),
        .capture_valid(capture_valid), .capture_status(capture_status),
        .capture_address(capture_address), .capture_data(capture_data),
        .capture_count(captures), .cpu_completed(completed)
    );
    integer ticks = 0, transactions = 0;
    reg active = 0;
    always @(posedge clk) begin
        ticks <= ticks + 1;
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        else if (mem_valid && !mem_rsp_valid) mem_rsp_valid <= 1;
        if (!reset) begin
            if (fault || error) $fatal(1, "launch bus card error address=%h uds=%b lds=%b rw=%b fault=%b error=%b offset=%h word=%b data=%h",
                address, uds_n, lds_n, rw_n, fault, error, card.req_offset, card.req_word, card.req_wdata);
            if (as_n) active <= 0;
            if (claim && !dtack_n && !active) begin
                transactions <= transactions + 1;
                active <= 1;
                $display("PDS address=%h rw=%0d uds=%0d lds=%0d data=%h", address, rw_n,
                         uds_n, lds_n, rw_n ? card_data : data_out);
                if (rw_n && address == 32'hFE000004 && card_data != 0)
                    $fatal(1, "idle capture address was not zero");
            end
            if (!as_n && !rw_n && address == 32'h00000200) begin
                if (data_out[15:8] != 8'h5A || transactions != 6 || completed || captures)
                    $fatal(1, "launch prefix completion mismatch");
                $display("PASS TG68K completes initial stop, idle address read and ACK before card execution");
                $finish;
            end
            if (ticks > 20000) $fatal(1, "launch bus timeout address=%h claim=%0d dtack=%0d error=%0d", address, claim, dtack_n, error);
        end
    end
    initial begin
        reg [4095:0] program_path;
        if (!$value$plusargs("program=%s", program_path)) $fatal(1, "missing host program");
        $readmemh(program_path, rom);
        repeat (10) @(negedge clk);
        reset = 0;
    end
endmodule
