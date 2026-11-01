// Experimental aliases and register widths follow the synthetic MAME adapter.
module card_pds_adapter (
    input wire clk,
    input wire reset,
    input wire [31:0] cpu_address,
    input wire [2:0] cpu_fc,
    input wire cpu_as_n,
    input wire cpu_uds_n,
    input wire cpu_lds_n,
    input wire cpu_rw,
    input wire [15:0] cpu_write_data,
    output wire claim,
    output wire dtack_n,
    output wire [15:0] cpu_read_data,
    output wire error,
    output wire req_valid,
    input wire req_ready,
    output reg [5:0] req_offset,
    output reg req_word,
    output reg req_write,
    output reg [15:0] req_wdata,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire [15:0] rsp_rdata,
    input wire rsp_error
);
    localparam BLOCK = 3'd0, IDLE = 3'd1, REQUEST = 3'd2,
               RESPONSE = 3'd3, DONE = 3'd4;
    reg [2:0] state = BLOCK;
    reg aborted = 0;
    reg upper_byte = 0;
    reg [15:0] response_data = 0;
    reg response_error = 0;
    wire alias_hit = (cpu_address >= 32'h80000000 && cpu_address < 32'h80000024)
                  || (cpu_address >= 32'h80E00000 && cpu_address < 32'h80E00024)
                  || (cpu_address >= 32'h00E00000 && cpu_address < 32'h00E00024);
    wire target = alias_hit && !cpu_address[0] && cpu_fc != 3'b111;
    wire strobed = !cpu_uds_n || !cpu_lds_n;
    wire active = state == REQUEST || state == RESPONSE || state == DONE;

    assign claim = !reset && !cpu_as_n && !aborted &&
                   ((state == IDLE && target) || active);
    assign req_valid = state == REQUEST && !reset && !cpu_as_n;
    assign rsp_ready = state == RESPONSE;
    assign dtack_n = !(claim && state == DONE && !response_error);
    assign cpu_read_data = response_data;
    assign error = claim && state == DONE && response_error;

    always @(posedge clk) begin
        case (state)
            BLOCK: begin
                aborted <= 0;
                if (!reset && cpu_as_n)
                    state <= IDLE;
            end
            IDLE: begin
                if (reset)
                    state <= BLOCK;
                else if (!cpu_as_n && strobed) begin
                    if (target) begin
                        req_offset <= {cpu_address[5:1], cpu_uds_n};
                        req_word <= !cpu_uds_n && !cpu_lds_n;
                        req_write <= !cpu_rw;
                        upper_byte <= !cpu_uds_n;
                        req_wdata <= !cpu_uds_n && !cpu_lds_n ? cpu_write_data :
                                     {8'h00, !cpu_uds_n ? cpu_write_data[15:8] : cpu_write_data[7:0]};
                        state <= REQUEST;
                    end else
                        state <= BLOCK;
                end
            end
            REQUEST: begin
                if (reset)
                    state <= BLOCK;
                else if (cpu_as_n)
                    state <= IDLE;
                else if (req_ready)
                    state <= RESPONSE;
            end
            RESPONSE: begin
                // Accepted transactions drain even if the CPU resets or aborts.
                if (reset || cpu_as_n)
                    aborted <= 1;
                if (rsp_valid) begin
                    if (reset || cpu_as_n || aborted) begin
                        aborted <= 0;
                        state <= !reset && cpu_as_n ? IDLE : BLOCK;
                    end
                    else begin
                        response_data <= req_word ? rsp_rdata :
                                         upper_byte ? {rsp_rdata[7:0], 8'hFF} :
                                                      {8'hFF, rsp_rdata[7:0]};
                        response_error <= rsp_error;
                        state <= DONE;
                    end
                end
            end
            DONE: begin
                if (reset)
                    state <= BLOCK;
                else if (cpu_as_n)
                    state <= IDLE;
            end
            default: state <= BLOCK;
        endcase
    end
endmodule
