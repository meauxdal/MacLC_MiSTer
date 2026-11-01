// Retain a level request through mailbox acceptance and the response tail.
module card_floppy_stop (
    input wire clk,
    input wire reset,
    input wire stop_request,
    output wire stopped,
    input wire req,
    input wire [23:0] addr,
    output wire ack,
    output wire valid,
    input wire ready,
    output reg [23:0] frozen_addr,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire mailbox_drained
);
    localparam IDLE = 2'd0, OFFER = 2'd1, RESPONSE = 2'd2, TAIL = 2'd3;
    reg [1:0] state;
    assign valid = state == OFFER;
    assign ack = state == RESPONSE && rsp_valid;
    assign rsp_ready = state == RESPONSE && !req;
    assign stopped = stop_request && state == IDLE && mailbox_drained;

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            frozen_addr <= 0;
        end else begin
            case (state)
                IDLE: if (!stop_request && req) begin
                    frozen_addr <= addr;
                    state <= OFFER;
                end
                OFFER: if (ready) state <= RESPONSE;
                RESPONSE: if (rsp_valid && !req) state <= TAIL;
                TAIL: if (!rsp_valid && mailbox_drained) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
