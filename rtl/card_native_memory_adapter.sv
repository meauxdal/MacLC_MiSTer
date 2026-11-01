// Same-clock experiment for the source-pinned MacLC spare SDRAM port.
`timescale 1ns/1ps
module card_native_memory_adapter #(
    parameter [23:0] BASE_WORD = 24'h540000,
    parameter integer WRITE_DRAIN_TICKS = 8
) (
    input wire clk,
    input wire por_n,
    input wire reset_request,
    output wire drained,
    input wire mem_valid,
    output wire mem_ready,
    input wire mem_write,
    input wire [16:0] mem_addr,
    input wire [15:0] mem_wdata,
    output wire mem_rsp_valid,
    input wire mem_rsp_ready,
    output reg [15:0] mem_rdata,
    output wire native_req,
    output reg native_we,
    output reg [23:0] native_addr,
    output reg [15:0] native_din,
    input wire native_ack,
    input wire [15:0] native_dout
);
    localparam IDLE = 3'd0, WAIT_ACK = 3'd1, WRITE_DRAIN = 3'd2,
               REARM = 3'd3, RESPONSE = 3'd4;
    reg [2:0] state;
    integer unsigned drain_ticks;

    assign mem_ready = por_n && !reset_request && state == IDLE && !native_ack;
    assign mem_rsp_valid = state == RESPONSE;
    assign native_req = state == WAIT_ACK || state == WRITE_DRAIN;
    assign drained = state == IDLE && !native_ack;

    always @(posedge clk) begin
        if (!por_n) begin
            state <= IDLE;
            drain_ticks <= 0;
            native_we <= 0;
            native_addr <= 0;
            native_din <= 0;
            mem_rdata <= 0;
        end else begin
            case (state)
                IDLE: if (mem_valid && mem_ready) begin
                    native_we <= mem_write;
                    native_addr <= BASE_WORD + {7'b0, mem_addr};
                    native_din <= mem_wdata;
                    state <= WAIT_ACK;
                end
                WAIT_ACK: if (native_ack) begin
                    if (native_we) begin
                        // ACK is ACTIVE, not CAS. Keep ownership through E7.
                        drain_ticks <= WRITE_DRAIN_TICKS;
                        mem_rdata <= 0;
                        state <= WRITE_DRAIN;
                    end else begin
                        mem_rdata <= native_dout;
                        state <= REARM;
                    end
                end
                WRITE_DRAIN: begin
                    if (drain_ticks <= 1) state <= REARM;
                    else drain_ticks <= drain_ticks - 1;
                end
                REARM: if (!native_ack) state <= RESPONSE;
                RESPONSE: if (mem_rsp_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
