// Split 128-bit canvas bursts into 64-bit DDRAM bursts of at most 128 beats.
module tv_ddram_bridge (
    input wire clk,
    input wire [27:0] source_address,
    input wire [7:0] source_burstcount,
    input wire [127:0] source_writedata,
    input wire [15:0] source_byteenable,
    input wire source_read, source_write,
    output wire source_waitrequest,
    output reg source_readdatavalid=0,
    output reg [127:0] source_readdata=0,
    output reg [28:0] address=0,
    output wire [7:0] burstcount,
    output wire [63:0] writedata,
    output wire [7:0] byteenable,
    output wire read, write,
    input wire waitrequest, readdatavalid,
    input wire [63:0] readdata
);
localparam [1:0] IDLE=0, READ_CMD=1, READ_DATA=2, WRITE_DATA=3;
reg [1:0] state=IDLE;
reg [7:0] remaining=0;
reg [6:0] chunk=0, words_left=0;
reg half=0, first_command=0;
reg [63:0] low_data=0;
wire [7:0] next_remaining=remaining-{1'b0,chunk};
wire accepted=(read || write) && !waitrequest;
assign burstcount={chunk,1'b0};
assign writedata=half ? source_writedata[127:64] : source_writedata[63:0];
assign byteenable=half ? source_byteenable[15:8] : source_byteenable[7:0];
assign read=state==READ_CMD;
assign write=state==WRITE_DATA && source_write;
assign source_waitrequest=!(accepted && ((state==READ_CMD && first_command) ||
                                        (state==WRITE_DATA && half)));
always @(posedge clk) begin
    source_readdatavalid<=0;
    case (state)
        IDLE: if (source_read || source_write) begin
            address<={source_address,1'b0};
            remaining<=source_burstcount;
            chunk<=source_burstcount>64 ? 7'd64 : source_burstcount[6:0];
            words_left<=source_burstcount>64 ? 7'd64 : source_burstcount[6:0];
            half<=0; first_command<=1;
            state<=source_read ? READ_CMD : WRITE_DATA;
        end
        READ_CMD: if (accepted) begin state<=READ_DATA; first_command<=0; end
        READ_DATA: if (readdatavalid) begin
            half<=!half;
            if (!half) low_data<=readdata;
            else begin
                source_readdata<={readdata,low_data};
                source_readdatavalid<=1;
                words_left<=words_left-1'b1;
                if (words_left==1) begin
                    remaining<=next_remaining;
                    address<=address+{21'd0,chunk,1'b0};
                    chunk<=next_remaining>64 ? 7'd64 : next_remaining[6:0];
                    words_left<=next_remaining>64 ? 7'd64 : next_remaining[6:0];
                    state<=next_remaining==0 ? IDLE : READ_CMD;
                end
            end
        end
        WRITE_DATA: if (accepted) begin
            half<=!half;
            if (half) begin
                words_left<=words_left-1'b1;
                if (words_left==1) begin
                    remaining<=next_remaining;
                    address<=address+{21'd0,chunk,1'b0};
                    chunk<=next_remaining>64 ? 7'd64 : next_remaining[6:0];
                    words_left<=next_remaining>64 ? 7'd64 : next_remaining[6:0];
                    if (next_remaining==0) state<=IDLE;
                end
            end
        end
    endcase
end
endmodule
