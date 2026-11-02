// Experimental card binding. Warm host reset preserves backend work.
module maclc_iie_binding (
    input wire clk_sys, clk_mem, pll_locked, memory_ready, host_reset,
    input wire runtime_mode,
    input wire [31:0] pds_address,
    input wire [2:0] pds_fc,
    input wire pds_as_n, pds_uds_n, pds_lds_n, pds_rw,
    input wire [15:0] pds_write_data,
    output wire diagnostic_boundary, diagnostic_fault,
    output wire [215:0] debug_status,
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
    wire [15:0] cpu_pc, cpu_bus, cap_address;
    wire cap_valid;
    wire [7:0] cap_status, cap_data;
    wire [31:0] cap_count, cpu_count;
    wire [3:0] debug_state;
    wire [15:0] debug_trace;
    reg bus_active = 0;
    reg [31:0] bus_count = 0, bus_address = 0;
    reg [15:0] bus_data = 0;
    always @(posedge clk_sys) begin
        if (!reset_sys[1]) begin
            bus_active <= 0;
            bus_count <= 0;
            bus_address <= 0;
            bus_data <= 0;
        end else begin
            if (pds_as_n) bus_active <= 0;
            else if (claim && !dtack_n && !bus_active) begin
                bus_active <= 1;
                bus_count <= bus_count + 32'd1;
                bus_address <= pds_address;
                bus_data <= pds_rw ? pds_read_data : pds_write_data;
            end
        end
    end
    assign debug_status = {debug_trace, debug_state, claim, cap_valid, diagnostic_boundary, diagnostic_fault,
        cpu_pc, cap_address, cap_status, cap_data, cpu_bus, cap_count[15:0], cpu_count, bus_count, bus_address, bus_data};
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
        .clk_sys(clk_sys), .clk_mem(clk_mem), .por_n_sys(reset_sys[1]), .runtime_mode(runtime_mode), .por_n_mem(reset_mem[1]),
        .host_reset(host_reset), .pds_address(card_address), .pds_fc(pds_fc),
        .pds_as_n(pds_as_n), .pds_uds_n(pds_uds_n), .pds_lds_n(pds_lds_n), .pds_rw(pds_rw),
        .pds_write_data(pds_write_data), .claim(claim), .dtack_n(dtack_n),
        .pds_read_data(pds_read_data), .error(error),
        .floppy_req(floppy_req), .floppy_addr(floppy_addr), .floppy_ack(floppy_ack), .floppy_data(floppy_data),
        .native_req(native_req), .native_we(native_we), .native_addr(native_addr), .native_din(native_din),
        .native_ack(native_ack), .native_dout(native_dout),
        .fault(diagnostic_fault), .boundary(diagnostic_boundary), .card_cpu_address(cpu_bus), .instruction_address(cpu_pc), .capture_valid(cap_valid), .capture_status(cap_status),
        .capture_address(cap_address), .capture_data(cap_data), .capture_count(cap_count), .cpu_completed(cpu_count), .debug_state(debug_state), .debug_trace(debug_trace)
    );
endmodule
