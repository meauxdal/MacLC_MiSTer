// Coordinated warm reset. Cold reset is external and must reset both domains.
`timescale 1ns/1ps
module card_warm_reset #(
    parameter integer INIT_TICKS = 16
) (
    input wire clk_sys,
    input wire clk_mem,
    input wire por_n_sys,
    input wire por_n_mem,
    input wire warm_request_sys,
    input wire download_active_sys,
    input wire producers_stopped_sys,
    input wire drained_sys,
    input wire native_drained_mem,
    input wire controller_ready_mem,
    input wire controller_idle_mem,
    output wire stop_sys,
    output wire stop_mem,
    output wire controller_quiesce,
    output wire controller_init,
    output wire epoch_reset_sys,
    output wire epoch_reset_mem,
    output wire busy,
    output reg completed
);
    localparam RUN = 3'd0, DRAIN = 3'd1, FREEZE = 3'd2, INIT = 3'd3,
               WAIT_READY = 3'd4, EPOCH = 3'd5, RELEASE = 3'd6;
    reg [2:0] state;
    integer unsigned init_count;
    reg pending, request_seen;
    (* ASYNC_REG = "TRUE" *) reg stop_sync1, stop_sync2, epoch_sync1, epoch_sync2;
    (* ASYNC_REG = "TRUE" *) reg request_sync1, request_sync2;
    (* ASYNC_REG = "TRUE" *) reg download_sync1, download_sync2;
    (* ASYNC_REG = "TRUE" *) reg stopped_sync1, stopped_sync2, drained_sync1, drained_sync2;
    (* ASYNC_REG = "TRUE" *) reg epoch_ack1, epoch_ack2;
    assign stop_mem = state != RUN;
    assign stop_sys = stop_sync2;
    assign controller_quiesce = state != RUN && state != DRAIN;
    assign controller_init = state == INIT;
    assign epoch_reset_mem = state == EPOCH;
    assign epoch_reset_sys = epoch_sync2;
    assign busy = state != RUN || pending;

    always @(posedge clk_sys) begin
        if (!por_n_sys) begin
            stop_sync1 <= 1;
            stop_sync2 <= 1;
            epoch_sync1 <= 0;
            epoch_sync2 <= 0;
        end else begin
            stop_sync1 <= stop_mem;
            stop_sync2 <= stop_sync1;
            epoch_sync1 <= epoch_reset_mem;
            epoch_sync2 <= epoch_sync1;
        end
    end
    always @(posedge clk_mem) begin
        if (!por_n_mem) begin
            state <= RUN;
            init_count <= 0;
            pending <= 0;
            request_seen <= 0;
            request_sync1 <= 0;
            request_sync2 <= 0;
            download_sync1 <= 0;
            download_sync2 <= 0;
            stopped_sync1 <= 0;
            stopped_sync2 <= 0;
            drained_sync1 <= 0;
            drained_sync2 <= 0;
            epoch_ack1 <= 0;
            epoch_ack2 <= 0;
            completed <= 0;
        end else begin
            request_sync1 <= warm_request_sys;
            request_sync2 <= request_sync1;
            download_sync1 <= download_active_sys;
            download_sync2 <= download_sync1;
            stopped_sync1 <= producers_stopped_sys;
            stopped_sync2 <= stopped_sync1;
            drained_sync1 <= drained_sys;
            drained_sync2 <= drained_sync1;
            epoch_ack1 <= epoch_reset_sys;
            epoch_ack2 <= epoch_ack1;
            completed <= 0;
            request_seen <= request_sync2;
            if (request_sync2 && !request_seen) pending <= 1;
            case (state)
                RUN: if (pending && !download_sync2 && controller_ready_mem) begin
                    pending <= 0;
                    state <= DRAIN;
                end
                DRAIN: if (stopped_sync2 && drained_sync2 && native_drained_mem && !download_sync2)
                    state <= FREEZE;
                FREEZE: if (controller_idle_mem && !download_sync2) begin
                    init_count <= INIT_TICKS;
                    state <= INIT;
                end
                INIT: if (init_count <= 1) state <= WAIT_READY;
                      else init_count <= init_count - 1;
                WAIT_READY: if (controller_ready_mem) state <= EPOCH;
                EPOCH: if (epoch_ack2) state <= RELEASE;
                RELEASE: if (!epoch_ack2 && drained_sync2 && native_drained_mem) begin
                    state <= RUN;
                    completed <= 1;
                end
                default: state <= RUN;
            endcase
        end
    end
endmodule
