// One outstanding bundled mailbox. Reset both domains only while quiescent.
module card_host_cdc (
    input wire src_clk,
    input wire src_reset,
    input wire dst_clk,
    input wire dst_reset,
    input wire src_valid,
    output wire src_ready,
    input wire [23:0] src_request,
    output wire src_rsp_valid,
    input wire src_rsp_ready,
    output reg [16:0] src_response,
    output wire drained,
    output wire dst_valid,
    input wire dst_ready,
    output reg [23:0] dst_request,
    input wire dst_rsp_valid,
    output wire dst_rsp_ready,
    input wire [16:0] dst_response
);
    localparam S_IDLE = 2'd0, S_WAIT = 2'd1, S_RESPONSE = 2'd2;
    localparam D_IDLE = 2'd0, D_SEND = 2'd1, D_WAIT = 2'd2;
    reg [1:0] src_state, dst_state;
    reg request_toggle, response_toggle, request_seen;
    reg [23:0] mailbox_request;
    reg [16:0] mailbox_response;
    (* ASYNC_REG = "TRUE" *) reg request_sync1, request_sync2;
    (* ASYNC_REG = "TRUE" *) reg response_sync1, response_sync2;

    assign src_ready = src_state == S_IDLE && !src_reset;
    assign src_rsp_valid = src_state == S_RESPONSE && !src_reset;
    assign drained = src_state == S_IDLE && request_toggle == response_sync2 && !src_reset;
    assign dst_valid = dst_state == D_SEND && !dst_reset;
    assign dst_rsp_ready = dst_state == D_WAIT && !dst_reset;

    always @(posedge src_clk) begin
        if (src_reset) begin
            src_state <= S_IDLE;
            request_toggle <= 0;
            response_sync1 <= 0;
            response_sync2 <= 0;
            mailbox_request <= 0;
            src_response <= 0;
        end else begin
            response_sync1 <= response_toggle;
            response_sync2 <= response_sync1;
            case (src_state)
                S_IDLE: if (src_valid) begin
                    mailbox_request <= src_request;
                    request_toggle <= !request_toggle;
                    src_state <= S_WAIT;
                end
                S_WAIT: if (response_sync2 == request_toggle) begin
                    src_response <= mailbox_response;
                    src_state <= S_RESPONSE;
                end
                S_RESPONSE: if (src_rsp_ready) src_state <= S_IDLE;
                default: src_state <= S_IDLE;
            endcase
        end
    end

    always @(posedge dst_clk) begin
        if (dst_reset) begin
            dst_state <= D_IDLE;
            request_sync1 <= 0;
            request_sync2 <= 0;
            request_seen <= 0;
            response_toggle <= 0;
            mailbox_response <= 0;
            dst_request <= 0;
        end else begin
            request_sync1 <= request_toggle;
            request_sync2 <= request_sync1;
            case (dst_state)
                D_IDLE: if (request_sync2 != request_seen) begin
                    // The source payload has settled during toggle synchronization.
                    dst_request <= mailbox_request;
                    request_seen <= request_sync2;
                    dst_state <= D_SEND;
                end
                D_SEND: if (dst_ready) dst_state <= D_WAIT;
                D_WAIT: if (dst_rsp_valid) begin
                    mailbox_response <= dst_response;
                    response_toggle <= request_seen;
                    dst_state <= D_IDLE;
                end
                default: dst_state <= D_IDLE;
            endcase
        end
    end
endmodule
