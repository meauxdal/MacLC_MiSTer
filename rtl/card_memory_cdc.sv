// One outstanding bundled mailbox. Reset both domains only while quiescent.
module card_memory_cdc #(
    parameter ADDR_WIDTH = 17
) (
    input wire src_clk,
    input wire src_reset,
    input wire dst_clk,
    input wire dst_reset,
    input wire src_valid,
    output wire src_ready,
    input wire src_write,
    input wire [ADDR_WIDTH-1:0] src_addr,
    input wire [15:0] src_wdata,
    output wire src_rsp_valid,
    input wire src_rsp_ready,
    output reg [15:0] src_rdata,
    output wire drained,
    output wire dst_valid,
    input wire dst_ready,
    output reg dst_write,
    output reg [ADDR_WIDTH-1:0] dst_addr,
    output reg [15:0] dst_wdata,
    input wire dst_rsp_valid,
    output wire dst_rsp_ready,
    input wire [15:0] dst_rdata
);
    localparam S_IDLE = 2'd0, S_WAIT = 2'd1, S_RESPONSE = 2'd2;
    localparam D_IDLE = 2'd0, D_SEND = 2'd1, D_WAIT = 2'd2;
    reg [1:0] src_state, dst_state;
    reg request_toggle, response_toggle, request_seen;
    reg mailbox_write;
    reg [ADDR_WIDTH-1:0] mailbox_addr;
    reg [15:0] mailbox_wdata, mailbox_rdata;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *) reg request_sync1, request_sync2;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *) reg response_sync1, response_sync2;

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
            mailbox_write <= 0;
            mailbox_addr <= 0;
            mailbox_wdata <= 0;
            src_rdata <= 0;
        end else begin
            response_sync1 <= response_toggle;
            response_sync2 <= response_sync1;
            case (src_state)
                S_IDLE: if (src_valid) begin
                    mailbox_write <= src_write;
                    mailbox_addr <= src_addr;
                    mailbox_wdata <= src_wdata;
                    request_toggle <= !request_toggle;
                    src_state <= S_WAIT;
                end
                S_WAIT: if (response_sync2 == request_toggle) begin
                    src_rdata <= mailbox_rdata;
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
            mailbox_rdata <= 0;
            dst_write <= 0;
            dst_addr <= 0;
            dst_wdata <= 0;
        end else begin
            request_sync1 <= request_toggle;
            request_sync2 <= request_sync1;
            case (dst_state)
                D_IDLE: if (request_sync2 != request_seen) begin
                    // The source payload has settled during toggle synchronization.
                    dst_write <= mailbox_write;
                    dst_addr <= mailbox_addr;
                    dst_wdata <= mailbox_wdata;
                    request_seen <= request_sync2;
                    dst_state <= D_SEND;
                end
                D_SEND: if (dst_ready) dst_state <= D_WAIT;
                D_WAIT: if (dst_rsp_valid) begin
                    mailbox_rdata <= dst_rdata;
                    response_toggle <= request_seen;
                    dst_state <= D_IDLE;
                end
                default: dst_state <= D_IDLE;
            endcase
        end
    end
endmodule
