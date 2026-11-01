// Same-clock experiment. Backend BE is native; write completion means commit.
`timescale 1ns/1ps
module card_byte_memory_arbiter (
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
    output reg mem_write,
    output reg [16:0] mem_addr,
    output reg [15:0] mem_wdata,
    output reg [1:0] mem_be,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rdata
);
    localparam IDLE = 2'd0, SEND = 2'd1, WAIT = 2'd2, RESPONSE = 2'd3;
    reg [1:0] state;
    reg owner, next_owner, selected;
    wire [17:0] address = selected ? card_addr : host_addr;
    wire [15:0] data_in = selected ? card_wdata : host_wdata;
    wire [1:0] enables = selected ? card_be : host_be;
    wire bad_lanes = enables == 0 || (enables == 3 && address[0]) ||
                     (enables == 1 && address[0]) || (enables == 2 && !address[0]);
    assign drained = state == IDLE;
    assign mem_valid = state == SEND;
    assign mem_rsp_ready = state == WAIT;
    always @* begin
        selected = req_valid == 3 ? next_owner : req_valid[1];
        req_ready = 0;
        if (state == IDLE && !reset_request && por_n) req_ready[selected] = 1;
        rsp_valid = 0;
        if (state == RESPONSE) rsp_valid[owner] = 1;
    end
    always @(posedge clk) begin
        if (!por_n) begin
            state <= IDLE;
            owner <= 0;
            next_owner <= 0;
            mem_write <= 0;
            mem_addr <= 0;
            mem_wdata <= 0;
            mem_be <= 0;
            rsp_rdata <= 0;
            rsp_denied <= 0;
        end else begin
            case (state)
                IDLE: if (req_valid[selected] && req_ready[selected]) begin
                    owner <= selected;
                    next_owner <= !selected;
                    mem_addr <= address[17:1];
                    mem_write <= req_write[selected];
                    mem_wdata <= data_in;
                    mem_be <= enables;
                    rsp_rdata <= 0;
                    rsp_denied <= bad_lanes || (req_write[selected] && !req_write_allowed[selected]);
                    state <= bad_lanes || (req_write[selected] && !req_write_allowed[selected]) ? RESPONSE : SEND;
                end
                SEND: if (mem_ready) state <= WAIT;
                WAIT: if (mem_rsp_valid) begin
                    rsp_rdata <= mem_write ? 16'b0 : mem_rdata;
                    state <= RESPONSE;
                end
                RESPONSE: if (rsp_ready[owner]) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
