// Candidate register geometry. Reset is a cold flush, not a host CPU reset.
module card_irq_host_registers (
    input wire clk,
    input wire reset,
    input wire req_valid,
    output wire req_ready,
    input wire [5:0] req_offset,
    input wire req_word,
    input wire req_write,
    input wire [15:0] req_wdata,
    output wire rsp_valid,
    input wire rsp_ready,
    output reg [15:0] rsp_rdata,
    output reg rsp_error,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output wire [17:0] mem_req_addr,
    output wire mem_req_write,
    output wire [15:0] mem_req_wdata,
    output wire [1:0] mem_req_be,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rsp_rdata,
    input wire mem_rsp_denied,
    output reg [7:0] control,
    output reg [15:0] index,
    input wire [7:0] capture_status,
    input wire [15:0] capture_address,
    input wire [7:0] capture_data,
    input wire [7:0] keyboard_status,
    input wire [7:0] opaque08,
    output reg sidefx_valid,
    output reg [5:0] sidefx_offset,
    output reg sidefx_word,
    output reg sidefx_write,
    output reg [15:0] sidefx_wdata,
    output wire ack_write,
    output wire read_release_write,
    output wire capture_address_read,
    output wire control_write,
    output wire command_write,
    output wire mask_write,
    output wire keyboard_write
);
    localparam IDLE = 2'd0, SEND = 2'd1, WAIT = 2'd2, RESPONSE = 2'd3;
    reg [1:0] state;
    reg [7:0] command_byte, host_mask;
    reg word_access, lane, second_lane, writing;
    reg context_bank;
    reg [15:0] stream_index, stream_data;
    wire [7:0] outgoing = word_access ? (second_lane ? stream_data[7:0] : stream_data[15:8])
                                              : stream_data[7:0];
    wire [7:0] incoming = stream_index[0] ? mem_rsp_rdata[15:8] : mem_rsp_rdata[7:0];
    assign req_ready = state == IDLE && !reset;
    assign rsp_valid = state == RESPONSE && !reset;
    assign mem_req_valid = state == SEND && !reset;
    assign mem_rsp_ready = state == WAIT && !reset;
    assign mem_req_addr = {context_bank, lane, stream_index};
    assign mem_req_write = writing;
    assign mem_req_wdata = {outgoing, outgoing};
    assign mem_req_be = stream_index[0] ? 2'b10 : 2'b01;
    assign ack_write = sidefx_valid && sidefx_write && !sidefx_word && sidefx_offset == 6'h0C;
    assign read_release_write = sidefx_valid && sidefx_write && !sidefx_word && sidefx_offset == 6'h19;
    assign capture_address_read = sidefx_valid && !sidefx_write && sidefx_word && sidefx_offset == 6'h04;
    assign control_write = sidefx_valid && sidefx_write && !sidefx_word && sidefx_offset == 6'h0D;
    assign command_write = sidefx_valid && sidefx_write && sidefx_offset == 6'h20;
    assign mask_write = sidefx_valid && sidefx_write && !sidefx_word && sidefx_offset == 6'h21;
    assign keyboard_write = sidefx_valid && sidefx_write && !sidefx_word && sidefx_offset == 6'h18;

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            control <= 0;
            command_byte <= 0;
            host_mask <= 0;
            index <= 0;
            rsp_rdata <= 0;
            rsp_error <= 0;
            word_access <= 0;
            lane <= 0;
            second_lane <= 0;
            writing <= 0;
            context_bank <= 0;
            stream_index <= 0;
            stream_data <= 0;
            sidefx_valid <= 0;
            sidefx_offset <= 0;
            sidefx_word <= 0;
            sidefx_write <= 0;
            sidefx_wdata <= 0;
        end else begin
            sidefx_valid <= 0;
            case (state)
                IDLE: if (req_valid) begin
                    rsp_rdata <= 0;
                    rsp_error <= 0;
                    if ((!req_word && (req_offset == 6'h10 || req_offset == 6'h11)) ||
                        (req_word && req_offset == 6'h10)) begin
                        word_access <= req_word;
                        lane <= req_word ? 1'b0 : req_offset[0];
                        second_lane <= 0;
                        context_bank <= control[3];
                        stream_index <= index;
                        stream_data <= req_wdata;
                        writing <= req_write;
                        state <= SEND;
                    end else begin
                        state <= RESPONSE;
                        sidefx_valid <= 1;
                        sidefx_offset <= req_offset;
                        sidefx_word <= req_word;
                        sidefx_write <= req_write;
                        sidefx_wdata <= req_wdata;
                        if (req_write) begin
                            case ({req_word, req_offset})
                                {1'b0, 6'h20}: command_byte <= req_wdata[7:0];
                                {1'b1, 6'h20}: command_byte <= req_wdata[15:8];
                                {1'b0, 6'h0D}: control <= req_wdata[7:0];
                                {1'b1, 6'h1C}: index <= req_wdata;
                                {1'b0, 6'h0C}, {1'b0, 6'h18}, {1'b0, 6'h19}: ;
                                {1'b0, 6'h21}: host_mask <= req_wdata[7:0];
                                default: begin rsp_error <= 1; sidefx_valid <= 0; end
                            endcase
                        end else begin
                            case ({req_word, req_offset})
                                {1'b0, 6'h01}: rsp_rdata <= {8'b0, capture_status};
                                {1'b1, 6'h04}: rsp_rdata <= capture_address;
                                {1'b0, 6'h08}: rsp_rdata <= {8'b0, opaque08};
                                {1'b0, 6'h09}: rsp_rdata <= {8'b0, keyboard_status};
                                {1'b0, 6'h0C}: rsp_rdata <= {8'b0, capture_data};
                                // CLR.B reads the release strobe before writing it.
                                {1'b0, 6'h19}: rsp_rdata <= 0;
                                {1'b0, 6'h20}: rsp_rdata <= {8'b0, command_byte};
                                {1'b1, 6'h20}: rsp_rdata <= {command_byte, host_mask};
                                {1'b0, 6'h21}: rsp_rdata <= {8'b0, host_mask};
                                {1'b0, 6'h0D}: rsp_rdata <= {8'b0, control};
                                {1'b1, 6'h1C}: rsp_rdata <= index;
                                default: begin rsp_error <= 1; sidefx_valid <= 0; end
                            endcase
                        end
                    end
                end
                SEND: if (mem_req_ready) state <= WAIT;
                WAIT: if (mem_rsp_valid) begin
                    if (mem_rsp_denied) begin
                        rsp_error <= 1;
                        state <= RESPONSE;
                    end else begin
                        if (!writing) begin
                            if (word_access && !second_lane) rsp_rdata[15:8] <= incoming;
                            else rsp_rdata[7:0] <= incoming;
                        end
                        if (word_access && !second_lane) begin
                            lane <= 1;
                            second_lane <= 1;
                            state <= SEND;
                        end else begin
                            index <= index + 16'd1;
                            state <= RESPONSE;
                        end
                    end
                end
                RESPONSE: if (rsp_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
