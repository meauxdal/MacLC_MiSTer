// Experimental diagnostic binding. Warm host reset preserves backend work.
module maclc_iie_binding (
    input wire clk_sys, clk_mem, pll_locked, memory_ready, host_reset,
    input wire [31:0] pds_address,
    input wire [2:0] pds_fc,
    input wire pds_as_n, pds_uds_n, pds_lds_n, pds_rw,
    input wire [15:0] pds_write_data,
    output wire claim, dtack_n, error,
    output wire [15:0] pds_read_data,
    input wire floppy_req,
    input wire [23:0] floppy_addr,
    output wire floppy_ack,
    output wire [15:0] floppy_data,
    output wire native_req, native_we,
    output wire [23:0] native_addr,
    output wire [15:0] native_din,
    input wire native_ack,
    input wire [15:0] native_dout
);
    wire cold_ready = pll_locked && memory_ready;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *) reg [1:0] reset_mem = 0;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *) reg [1:0] reset_sys = 0;
    always @(posedge clk_mem or negedge cold_ready)
        if (!cold_ready) reset_mem <= 0;
        else reset_mem <= {reset_mem[0], 1'b1};
    always @(posedge clk_sys or negedge cold_ready)
        if (!cold_ready) reset_sys <= 0;
        else reset_sys <= {reset_sys[0], 1'b1};
    // Translate full LC slot addresses to the adapter's MAME-masked aliases.
    wire [31:0] card_address = pds_address[31:24] == 8'hFE ?
                               {8'h80, pds_address[23:0]} : pds_address;
    card_platform #(.BASE_WORD(24'h540000)) platform (
        .clk_sys(clk_sys), .clk_mem(clk_mem), .por_n_sys(reset_sys[1]), .por_n_mem(reset_mem[1]),
        .host_reset(host_reset), .pds_address(card_address), .pds_fc(pds_fc),
        .pds_as_n(pds_as_n), .pds_uds_n(pds_uds_n), .pds_lds_n(pds_lds_n), .pds_rw(pds_rw),
        .pds_write_data(pds_write_data), .claim(claim), .dtack_n(dtack_n),
        .pds_read_data(pds_read_data), .error(error),
        .floppy_req(floppy_req), .floppy_addr(floppy_addr), .floppy_ack(floppy_ack), .floppy_data(floppy_data),
        .native_req(native_req), .native_we(native_we), .native_addr(native_addr), .native_din(native_din),
        .native_ack(native_ack), .native_dout(native_dout),
        .fault(), .boundary(), .card_cpu_address(), .capture_valid(), .capture_status(),
        .capture_address(), .capture_data(), .capture_count(), .cpu_completed()
    );
endmodule
