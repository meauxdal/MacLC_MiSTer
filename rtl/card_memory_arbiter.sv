// Standalone experiment. All channels use clk; backend completion means commit.
`timescale 1ns/1ps
module card_memory_arbiter #(
    parameter bit HOST_PRIORITY = 0
) (
    input wire clk,
    input wire por_n,
    input wire reset_request,
    output wire drained,
    input wire [1:0] req_valid,
    output reg [1:0] req_ready,
    input wire [1:0] req_write,
    input wire [1:0] req_write_allowed,
    input wire [17:0] host_addr,
    input wire [17:0] card_addr,
    input wire [15:0] host_wdata,
    input wire [15:0] card_wdata,
    input wire [1:0] host_be,
    input wire [1:0] card_be,
    output reg [1:0] rsp_valid,
    input wire [1:0] rsp_ready,
    output reg [15:0] rsp_rdata,
    output reg rsp_denied,
    output wire mem_valid,
    input wire mem_ready,
    output wire mem_write,
    output reg [16:0] mem_addr,
    output reg [15:0] mem_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rdata
);
    localparam IDLE = 3'd0, READ_SEND = 3'd1, READ_WAIT = 3'd2,
               WRITE_SEND = 3'd3, WRITE_WAIT = 3'd4, RESPONSE = 3'd5;
    reg [2:0] state;
    reg owner, next_owner, partial_write;
    reg [1:0] byte_enable;
    reg [15:0] write_data;
    reg selected;
    wire [17:0] address = selected ? card_addr : host_addr;
    wire [15:0] data_in = selected ? card_wdata : host_wdata;
    wire [1:0] enables = selected ? card_be : host_be;
    wire bad_lanes = (enables == 0) ||
                     ((enables == 2'b11) && address[0]) ||
                     ((enables == 2'b01) && address[0]) ||
                     ((enables == 2'b10) && !address[0]);

    assign drained = state == IDLE;
    assign mem_valid = (state == READ_SEND) || (state == WRITE_SEND);
    assign mem_write = state == WRITE_SEND;
    assign mem_rsp_ready = (state == READ_WAIT) || (state == WRITE_WAIT);

    always @* begin
        selected = 0;
        if (req_valid == 2'b11) selected = HOST_PRIORITY ? 1'b0 : next_owner;
        else if (req_valid[1]) selected = 1;
        req_ready = 0;
        if ((state == IDLE) && !reset_request && por_n)
            req_ready[selected] = 1;
        rsp_valid = 0;
        if (state == RESPONSE) rsp_valid[owner] = 1;
    end

    always @(posedge clk) begin
        if (!por_n) begin
            state <= IDLE;
            owner <= 0;
            next_owner <= 0;
            partial_write <= 0;
            byte_enable <= 0;
            write_data <= 0;
            mem_addr <= 0;
            mem_wdata <= 0;
            rsp_rdata <= 0;
            rsp_denied <= 0;
        end else begin
            case (state)
                IDLE: if (req_valid[selected] && req_ready[selected]) begin
                    owner <= selected;
                    next_owner <= !selected;
                    mem_addr <= address[17:1];
                    mem_wdata <= data_in;
                    write_data <= data_in;
                    byte_enable <= enables;
                    partial_write <= req_write[selected] && (enables != 2'b11);
                    rsp_rdata <= 0;
                    rsp_denied <= bad_lanes ||
                                  (req_write[selected] && !req_write_allowed[selected]);
                    if (bad_lanes || (req_write[selected] && !req_write_allowed[selected]))
                        state <= RESPONSE;
                    else if (req_write[selected] && (enables == 2'b11))
                        state <= WRITE_SEND;
                    else state <= READ_SEND;
                end
                READ_SEND: if (mem_ready) state <= READ_WAIT;
                READ_WAIT: if (mem_rsp_valid) begin
                    if (partial_write) begin
                        mem_wdata <= {byte_enable[1] ? write_data[15:8] : mem_rdata[15:8],
                                      byte_enable[0] ? write_data[7:0] : mem_rdata[7:0]};
                        state <= WRITE_SEND;
                    end else begin
                        rsp_rdata <= mem_rdata;
                        state <= RESPONSE;
                    end
                end
                WRITE_SEND: if (mem_ready) state <= WRITE_WAIT;
                WRITE_WAIT: if (mem_rsp_valid) state <= RESPONSE;
                RESPONSE: if (rsp_ready[owner]) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
