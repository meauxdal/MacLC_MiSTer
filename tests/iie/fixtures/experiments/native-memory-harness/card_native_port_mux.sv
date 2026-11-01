// Same-clock level-handshake ownership. Client 0 is card, client 1 is floppy.
`timescale 1ns/1ps
module card_native_port_mux (
    input wire clk,
    input wire por_n,
    input wire reset_request,
    output wire drained,
    input wire [1:0] client_req,
    input wire [1:0] client_we,
    input wire [23:0] card_addr,
    input wire [23:0] floppy_addr,
    input wire [15:0] card_din,
    input wire [15:0] floppy_din,
    output reg [1:0] client_ack,
    output wire [15:0] card_dout,
    output wire [15:0] floppy_dout,
    output wire native_req,
    output reg native_we,
    output reg [23:0] native_addr,
    output reg [15:0] native_din,
    input wire native_ack,
    input wire [15:0] native_dout
);
    localparam IDLE = 2'd0, ACTIVE = 2'd1, TURN = 2'd2;
    reg [1:0] state;
    reg owner, next_owner, ack_seen;
    wire selected = client_req == 2'b11 ? next_owner : client_req[1];
    wire owned = state != IDLE;

    assign drained = state == IDLE && !native_ack;
    assign native_req = state == ACTIVE && (client_req[owner] || !ack_seen);
    assign card_dout = owned && !owner ? native_dout : 16'b0;
    assign floppy_dout = owned && owner ? native_dout : 16'b0;
    always @* begin
        client_ack = 0;
        if (owned) client_ack[owner] = native_ack;
    end

    always @(posedge clk) begin
        if (!por_n) begin
            state <= IDLE;
            owner <= 0;
            next_owner <= 0;
            ack_seen <= 0;
            native_we <= 0;
            native_addr <= 0;
            native_din <= 0;
        end else begin
            case (state)
                IDLE: if (!reset_request && !native_ack && |client_req) begin
                    owner <= selected;
                    next_owner <= !selected;
                    native_we <= client_we[selected];
                    native_addr <= selected ? floppy_addr : card_addr;
                    native_din <= selected ? floppy_din : card_din;
                    ack_seen <= 0;
                    state <= ACTIVE;
                end
                ACTIVE: begin
                    if (native_ack) ack_seen <= 1;
                    if ((ack_seen || native_ack) && !client_req[owner]) state <= TURN;
                end
                TURN: if (!native_ack) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
