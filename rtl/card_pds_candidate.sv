// Experimental same-clock PDS adapter and card runtime.
module card_irq_pds_candidate (
    input wire clk,
    input wire runtime_mode,
    input wire por_n,
    input wire host_reset,
    input wire [31:0] pds_address,
    input wire [2:0] pds_fc,
    input wire pds_as_n,
    input wire pds_uds_n,
    input wire pds_lds_n,
    input wire pds_rw,
    input wire [15:0] pds_write_data,
    output wire claim,
    output wire dtack_n,
    output wire [15:0] pds_read_data,
    output wire error,
    output wire mem_valid,
    input wire mem_ready,
    output wire mem_write,
    output wire [16:0] mem_addr,
    output wire [15:0] mem_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rdata,
    output wire fault,
    output wire boundary,
    output wire [15:0] card_cpu_address,
    output wire [15:0] instruction_address,
    output wire capture_valid,
    output wire [7:0] capture_status,
    output wire [15:0] capture_address,
    output wire [7:0] capture_data,
    output wire [31:0] capture_count,
    output wire [31:0] cpu_completed,
    output wire [3:0] debug_state,
    output wire [71:0] debug_trace
);
    wire req_valid, req_ready, req_word, req_write;
    wire [5:0] req_offset;
    wire [15:0] req_wdata, rsp_rdata;
    wire rsp_valid, rsp_ready, rsp_error;
    card_pds_adapter pds (
        .clk(clk), .reset(host_reset || !por_n), .cpu_address(pds_address), .cpu_fc(pds_fc),
        .cpu_as_n(pds_as_n), .cpu_uds_n(pds_uds_n), .cpu_lds_n(pds_lds_n),
        .cpu_rw(pds_rw), .cpu_write_data(pds_write_data), .claim(claim), .dtack_n(dtack_n),
        .cpu_read_data(pds_read_data), .error(error), .req_valid(req_valid), .req_ready(req_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error)
    );
    card_irq_candidate card (
        .clk(clk), .por_n(por_n), .runtime_mode(runtime_mode), .req_valid(req_valid), .req_ready(req_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_valid(mem_valid), .mem_ready(mem_ready), .mem_write(mem_write), .mem_addr(mem_addr),
        .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid), .mem_rsp_ready(mem_rsp_ready),
        .mem_rdata(mem_rdata), .fault(fault), .boundary(boundary), .cpu_address(card_cpu_address), .instruction_address(instruction_address),
        .capture_valid(capture_valid), .capture_status(capture_status), .capture_address(capture_address),
        .capture_data(capture_data), .capture_count(capture_count), .cpu_completed(cpu_completed), .debug_state(debug_state), .debug_trace(debug_trace)
    );
endmodule
