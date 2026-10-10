// One-beat Ethernet commands. Payloads stay held until the toggle round trip.
// Reset abandons the client response; a submitted memory command still drains.
module tv_ddram_cdc (
    input wire clk_source, reset_source, clk_mem,
    input wire [28:0] source_address,
    input wire [63:0] source_writedata,
    input wire [7:0] source_byteenable,
    input wire source_read, source_write,
    output wire source_waitrequest, source_readdatavalid,
    output reg [63:0] source_readdata=0,
    output reg [28:0] address=0,
    output reg [63:0] writedata=0,
    output reg [7:0] byteenable=0,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [63:0] readdata
);
localparam [1:0] IDLE=0, WAIT=1, ACCEPT=2, RESPONSE=3;
reg [1:0] source_state=IDLE, mem_state=IDLE;
reg request=0, acknowledge=0, reading=0, abandoned=0;
reg [101:0] command_payload=0;
reg [63:0] response_payload=0;
(* preserve, dont_merge *) reg request_meta=0, request_sync=0;
(* preserve, dont_merge *) reg acknowledge_meta=0, acknowledge_sync=0;
assign source_waitrequest=source_state!=ACCEPT || abandoned || reset_source;
assign source_readdatavalid=source_state==RESPONSE && !abandoned && !reset_source;
assign read=mem_state==WAIT && reading;
assign write=mem_state==WAIT && !reading;
always @(posedge clk_source) begin
    acknowledge_meta<=acknowledge; acknowledge_sync<=acknowledge_meta;
    if (reset_source && source_state!=IDLE) abandoned<=1;
    case (source_state)
        IDLE: if (!reset_source && (source_read || source_write)) begin
            command_payload<={source_read,source_address,source_writedata,source_byteenable};
            request<=!request; abandoned<=0; source_state<=WAIT;
        end
        WAIT: if (acknowledge_sync==request) begin
            source_readdata<=response_payload;
            source_state<=abandoned || reset_source ? IDLE : ACCEPT;
        end
        ACCEPT: source_state<=command_payload[101] && !abandoned && !reset_source ? RESPONSE : IDLE;
        RESPONSE: source_state<=IDLE;
    endcase
end
always @(posedge clk_mem) begin
    request_meta<=request; request_sync<=request_meta;
    case (mem_state)
        IDLE: if (request_sync!=acknowledge) begin
            {reading,address,writedata,byteenable}<=command_payload;
            mem_state<=WAIT;
        end
        WAIT: if (!waitrequest) begin
            if (!reading || readdatavalid) begin
                response_payload<=readdata; acknowledge<=request_sync; mem_state<=IDLE;
            end else mem_state<=RESPONSE;
        end
        RESPONSE: if (readdatavalid) begin
            response_payload<=readdata; acknowledge<=request_sync; mem_state<=IDLE;
        end
        ACCEPT: ;
    endcase
end
endmodule
