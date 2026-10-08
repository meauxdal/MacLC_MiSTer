// RGBx triple buffering. One memory-domain authority owns FREE/WRITING/
// READY/DISPLAYING slots; one latest READY and one DISPLAYING at most.
// Region [0x21800000,0x21c00000) is disjoint from ASCAL's three 8MiB
// slots [0x20000000,0x21800000), and Main FB at 0x22000000.
// Avalon addresses are 16-byte words. Writes stage complete 16-beat bursts
// before presentation; reads prefetch a complete native line as one burst.
module tv_frame_store #(
    parameter [27:0] BASE_WORD = 28'h2180000
) (
    input wire clk,
    input wire inhibit, // platform/core reset: stop new commands, drain old
    input wire fifo_empty, fifo_valid,
    input wire [133:0] fifo_data,
    output wire fifo_pop,
    input wire pair_req,
    output reg pair_ack=0,
    input wire line_req,
    input wire [9:0] line_payload, // bank,canvas row; held until line_ack
    output reg line_ack=0,
    output reg line_we=0,
    output reg [8:0] line_addr=0, // bank + 8-bit word index
    output reg [127:0] line_data=0,
    output reg [27:0] address=0,
    output reg [7:0] burstcount=1,
    output reg [127:0] writedata=0,
    output wire [15:0] byteenable,
    output reg read=0, write=0,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata,
    output reg [31:0] published=0, dropped=0, repeated=0,
    output reg [1:0] display_slot=0,
    output reg display_valid=0
);
localparam [16:0] SLOT_WORDS=17'd76800; // 640*480*4/16
localparam [2:0] IDLE=0, POP=1, TOKEN=2, WRITE=3, CLEAR=4, READ_CMD=5, READ_DATA=6;
reg [2:0] state=IDLE;
(* ramstyle="M10K, no_rw_check" *) reg [127:0] write_buffer [0:15];
reg [3:0] fill_index=0, write_index=0;
reg writing=0, ready=0, frame_bad=1;
reg [1:0] write_slot=0, ready_slot=0, write_geometry=0, ready_geometry=0, display_geometry=0;
reg [16:0] write_count=0;
reg [7:0] clear_index=0, read_index=0, read_words=0, read_offset=0;
reg bank=0;
reg current_line_req=0;
(* async_reg="true" *) reg pair_meta=0, pair_sync=0, line_meta=0, line_sync=0;
wire [16:0] expected_words = write_geometry==2 ? 17'd76800 :
                            write_geometry==1 ? 17'd49152 : 17'd43776;
wire [8:0] origin_y = display_geometry==2 ? 9'd0 : display_geometry==1 ? 9'd48 : 9'd69;
wire [8:0] source_height = display_geometry==2 ? 9'd480 : display_geometry==1 ? 9'd384 : 9'd342;
wire [8:0] requested_y = line_payload[8:0];
wire image_line = display_valid && requested_y>=origin_y && requested_y-origin_y<source_height;
wire [8:0] source_y = requested_y-origin_y;
wire [7:0] words_per_line = display_geometry==2 ? 8'd160 : 8'd128;
wire [1:0] free_slot = (!display_valid || display_slot!=0) && (!ready || ready_slot!=0) ? 2'd0 :
                       (!display_valid || display_slot!=1) && (!ready || ready_slot!=1) ? 2'd1 : 2'd2;
assign byteenable=16'hffff;
assign fifo_pop=state==POP && !fifo_empty;
always @(posedge clk) begin
    pair_meta<=pair_req; pair_sync<=pair_meta;
    line_meta<=line_req; line_sync<=line_meta;
    line_we<=0;
    case (state)
        IDLE: begin
            if (pair_sync!=pair_ack) begin
                // Only when no accepted read/write remains in flight.
                if (ready) begin
                    display_slot<=ready_slot; display_geometry<=ready_geometry;
                    display_valid<=1; ready<=0;
                end else repeated<=repeated+1'b1;
                pair_ack<=pair_sync;
            end else if (!inhibit && line_sync!=line_ack) begin
                bank<=line_payload[9]; current_line_req<=line_sync;
                clear_index<=0; state<=CLEAR;
                read_words<=image_line ? words_per_line : 8'd0;
                read_offset<=display_geometry==2 ? 8'd0 : 8'd16;
                address<=BASE_WORD + 28'(display_slot)*28'(SLOT_WORDS) +
                         28'(source_y)*28'(words_per_line);
                burstcount<=words_per_line;
            end else if (!fifo_empty) state<=POP;
        end
        POP: if (!fifo_empty) state<=TOKEN;
        TOKEN: if (fifo_valid) begin
            if (fifo_data[133] && fifo_data[132]) begin
                if (writing) dropped<=dropped+1'b1;
                writing<=1; write_slot<=free_slot; write_geometry<=fifo_data[129:128];
                frame_bad<=fifo_data[130] || inhibit; write_count<=0; fill_index<=0;
                state<=IDLE;
            end else if (fifo_data[133] && fifo_data[131]) begin
                if (writing && !frame_bad && !fifo_data[130] && write_count==expected_words && fill_index==0 && !inhibit) begin
                    if (ready) dropped<=dropped+1'b1;
                    ready<=1; ready_slot<=write_slot; ready_geometry<=write_geometry;
                    published<=published+1'b1;
                end else dropped<=dropped+1'b1;
                writing<=0; state<=IDLE;
            end else if (writing && !inhibit && write_count<expected_words) begin
                frame_bad<=frame_bad || fifo_data[130] || fifo_data[129:128]!=write_geometry;
                write_buffer[fill_index]<=fifo_data[127:0];
                fill_index<=fill_index+1'b1;
                if (fill_index==15) begin
                    address<=BASE_WORD + 28'(write_slot)*28'(SLOT_WORDS) + 28'(write_count);
                    burstcount<=16; writedata<=write_buffer[0]; write<=1; write_index<=0; state<=WRITE;
                end else state<=IDLE;
            end else begin frame_bad<=1; state<=IDLE; end
        end
        WRITE: if (!waitrequest) begin
            write_count<=write_count+1'b1;
            write_index<=write_index+1'b1;
            writedata<=write_buffer[4'(write_index+1'b1)];
            if (write_index==15) begin write<=0; state<=IDLE; end
        end
        CLEAR: begin
            line_we<=1; line_addr<={bank,clear_index}; line_data<=0;
            if (clear_index==159) begin
                if (read_words==0) begin line_ack<=current_line_req; state<=IDLE; end
                else begin read<=1; read_index<=0; state<=READ_CMD; end
            end else clear_index<=clear_index+1'b1;
        end
        READ_CMD: begin
            if (!waitrequest) begin read<=0; state<=READ_DATA; end
            // Supports zero-latency Avalon response as well as delayed data.
            if (readdatavalid) begin
                line_we<=1; line_addr<={bank,read_offset}; line_data<=readdata; read_index<=1;
            end
        end
        READ_DATA: if (readdatavalid) begin
            line_we<=1; line_addr<={bank,8'(read_offset+read_index)}; line_data<=readdata;
            read_index<=read_index+1'b1;
            if (read_index==read_words-1'b1) begin line_ack<=current_line_req; state<=IDLE; end
        end
        default: state<=IDLE;
    endcase
    // Accepted/presented commands are never withdrawn on guest reset.
    if (inhibit) frame_bad<=1;
end
endmodule
