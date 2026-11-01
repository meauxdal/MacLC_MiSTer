// Experimental normalized-PDS CDC; card CPU and memory frontend use clk_mem.
`timescale 1ns/1ps
module card_frontend_platform #(
    parameter [23:0] BASE_WORD = 24'h540000
) (
    input wire clk_sys,
    input wire clk_mem,
    input wire por_n_sys,
    input wire por_n_mem,
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
    input wire floppy_req,
    input wire [23:0] floppy_addr,
    output wire floppy_ack,
    output wire [15:0] floppy_data,
    output wire native_req,
    output wire native_we,
    output wire [23:0] native_addr,
    output wire [15:0] native_din,
    input wire native_ack,
    input wire [15:0] native_dout,
    output wire fault,
    output wire boundary,
    output wire [15:0] card_cpu_address,
    output wire capture_valid,
    output wire [7:0] capture_status,
    output wire [15:0] capture_address,
    output wire [7:0] capture_data,
    output wire [31:0] capture_count,
    output wire [31:0] cpu_completed
);
    wire pds_req_valid, pds_req_ready, pds_req_word, pds_req_write;
    wire [5:0] pds_req_offset;
    wire [15:0] pds_req_wdata;
    wire pds_rsp_valid, pds_rsp_ready;
    wire [16:0] pds_response;
    wire host_req_valid, host_req_ready, host_rsp_valid, host_rsp_ready;
    wire [23:0] host_request;
    wire [15:0] host_rsp_data;
    wire host_rsp_error;
    wire dst_valid, dst_ready, dst_write, dst_rsp_valid, dst_rsp_ready;
    wire [16:0] dst_addr;
    wire [15:0] dst_wdata, dst_rdata;
    wire card_req, card_we;
    wire [23:0] card_addr;
    wire [15:0] card_din, card_dout;
    wire [1:0] client_ack;
    wire floppy_dst_valid, floppy_dst_ready, floppy_rsp_valid, floppy_rsp_ready;
    wire [23:0] floppy_dst_addr;
    wire [15:0] floppy_response;
    reg floppy_active, floppy_response_valid;
    reg [23:0] floppy_frozen_addr;
    reg [15:0] floppy_frozen_data;
    wire [15:0] floppy_native_data;

    card_pds_adapter pds (
        .clk(clk_sys), .reset(!por_n_sys || host_reset), .cpu_address(pds_address), .cpu_fc(pds_fc),
        .cpu_as_n(pds_as_n), .cpu_uds_n(pds_uds_n), .cpu_lds_n(pds_lds_n), .cpu_rw(pds_rw),
        .cpu_write_data(pds_write_data), .claim(claim), .dtack_n(dtack_n), .cpu_read_data(pds_read_data),
        .error(error), .req_valid(pds_req_valid), .req_ready(pds_req_ready), .req_offset(pds_req_offset),
        .req_word(pds_req_word), .req_write(pds_req_write), .req_wdata(pds_req_wdata),
        .rsp_valid(pds_rsp_valid), .rsp_ready(pds_rsp_ready), .rsp_rdata(pds_response[15:0]),
        .rsp_error(pds_response[16])
    );
    card_host_cdc host_crossing (
        .src_clk(clk_sys), .src_reset(!por_n_sys), .dst_clk(clk_mem), .dst_reset(!por_n_mem),
        .src_valid(pds_req_valid), .src_ready(pds_req_ready),
        .src_request({pds_req_offset, pds_req_word, pds_req_write, pds_req_wdata}),
        .src_rsp_valid(pds_rsp_valid), .src_rsp_ready(pds_rsp_ready), .src_response(pds_response), .drained(),
        .dst_valid(host_req_valid), .dst_ready(host_req_ready), .dst_request(host_request),
        .dst_rsp_valid(host_rsp_valid), .dst_rsp_ready(host_rsp_ready),
        .dst_response({host_rsp_error, host_rsp_data})
    );
    card_candidate card (
        .clk(clk_mem), .por_n(por_n_mem), .req_valid(host_req_valid), .req_ready(host_req_ready),
        .req_offset(host_request[23:18]), .req_word(host_request[17]), .req_write(host_request[16]),
        .req_wdata(host_request[15:0]), .rsp_valid(host_rsp_valid), .rsp_ready(host_rsp_ready),
        .rsp_rdata(host_rsp_data), .rsp_error(host_rsp_error), .mem_valid(dst_valid), .mem_ready(dst_ready),
        .mem_write(dst_write), .mem_addr(dst_addr), .mem_wdata(dst_wdata), .mem_rsp_valid(dst_rsp_valid),
        .mem_rsp_ready(dst_rsp_ready), .mem_rdata(dst_rdata), .fault(fault), .boundary(boundary),
        .cpu_address(card_cpu_address), .capture_valid(capture_valid), .capture_status(capture_status),
        .capture_address(capture_address), .capture_data(capture_data),
        .capture_count(capture_count), .cpu_completed(cpu_completed)
    );
    card_native_memory_adapter #(.BASE_WORD(BASE_WORD)) adapter (
        .clk(clk_mem), .por_n(por_n_mem), .reset_request(1'b0), .drained(),
        .mem_valid(dst_valid), .mem_ready(dst_ready), .mem_write(dst_write),
        .mem_addr(dst_addr), .mem_wdata(dst_wdata), .mem_rsp_valid(dst_rsp_valid),
        .mem_rsp_ready(dst_rsp_ready), .mem_rdata(dst_rdata), .native_req(card_req),
        .native_we(card_we), .native_addr(card_addr), .native_din(card_din),
        .native_ack(client_ack[0]), .native_dout(card_dout)
    );
    // Hold the source response until the existing level requester drops REQ.
    card_memory_cdc #(.ADDR_WIDTH(24)) floppy_crossing (
        .src_clk(clk_sys), .src_reset(!por_n_sys), .dst_clk(clk_mem), .dst_reset(!por_n_mem),
        .src_valid(floppy_req), .src_ready(), .src_write(1'b0), .src_addr(floppy_addr),
        .src_wdata(16'b0), .src_rsp_valid(floppy_rsp_valid), .src_rsp_ready(!floppy_req),
        .src_rdata(floppy_response), .dst_valid(floppy_dst_valid), .dst_ready(floppy_dst_ready),
        .dst_write(), .dst_addr(floppy_dst_addr), .dst_wdata(),
        .dst_rsp_valid(floppy_response_valid), .dst_rsp_ready(floppy_rsp_ready),
        .dst_rdata(floppy_frozen_data), .drained()
    );
    assign floppy_ack = floppy_rsp_valid;
    assign floppy_data = floppy_response;
    assign floppy_dst_ready = !floppy_active && !floppy_response_valid && !client_ack[1];
    always @(posedge clk_mem) begin
        if (!por_n_mem) begin
            floppy_active <= 0;
            floppy_response_valid <= 0;
            floppy_frozen_addr <= 0;
            floppy_frozen_data <= 0;
        end else begin
            if (floppy_dst_valid && floppy_dst_ready) begin
                floppy_frozen_addr <= floppy_dst_addr;
                floppy_active <= 1;
            end
            if (floppy_active && client_ack[1]) begin
                floppy_frozen_data <= floppy_native_data;
                floppy_response_valid <= 1;
                floppy_active <= 0;
            end
            if (floppy_response_valid && floppy_rsp_ready) floppy_response_valid <= 0;
        end
    end
    card_native_port_mux ownership (
        .clk(clk_mem), .por_n(por_n_mem), .reset_request(1'b0), .drained(),
        .client_req({floppy_active, card_req}), .client_we({1'b0, card_we}),
        .card_addr(card_addr), .floppy_addr(floppy_frozen_addr), .card_din(card_din),
        .floppy_din(16'b0), .client_ack(client_ack), .card_dout(card_dout),
        .floppy_dout(floppy_native_data), .native_req(native_req), .native_we(native_we),
        .native_addr(native_addr), .native_din(native_din),
        .native_ack(native_ack), .native_dout(native_dout)
    );
endmodule
