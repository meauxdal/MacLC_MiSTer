// One owner manages three RGBx slots. Only complete frames become DISPLAYING;
// pair selection holds dimensions and storage through both electrical fields.
// Avalon addresses count 16-byte words. Accepted commands always drain.
module tv_frame_store #(
    parameter [27:0] BASE_WORD = 28'h2180000,
    parameter SOURCE_WIDTH = 0, SOURCE_HEIGHT = 0
) (
    input wire clk, inhibit,
    input wire fifo_empty, fifo_valid,
    input wire [133:0] fifo_data,
    output wire fifo_pop,
    input wire pair_req,
    output reg pair_ack=0,
    input wire line_req,
    input wire [9:0] line_payload,
    output reg line_ack=0,
    output reg line_we=0,
    output reg [8:0] line_addr=0,
    output reg [127:0] line_data=0,
    output reg [27:0] address=0,
    output reg [7:0] burstcount=1,
    output wire [127:0] writedata,
    output wire [15:0] byteenable,
    output reg read=0, write=0,
    input wire waitrequest, readdatavalid,
    input wire [127:0] readdata,
    output reg [31:0] published=0, dropped=0, repeated=0,
    output reg [1:0] display_slot=0,
    output reg display_valid=0,
    output reg [9:0] display_width=0,
    output reg [8:0] display_height=0
);
localparam [27:0] SLOT_WORDS=28'd76800;
localparam [3:0] IDLE=0, POP=1, TOKEN=2, WRITE=3, CALCULATE=4, READ_CMD=5, READ_DATA=6, FINISH=7, WRITE_PREP=8;
reg [3:0] state=IDLE;
(* ramstyle="M10K, no_rw_check" *) reg [127:0] write_buffer [0:15];
reg [3:0] fill_index=0, write_index=0;
reg [127:0] buffered_word;
wire [3:0] buffer_read_addr=state==WRITE_PREP ? 4'd0 : write_index+4'd1;
// A single registered read port holds the current beat through backpressure.
always @(posedge clk) begin
    if (state==TOKEN && fifo_valid && (!fifo_data[133] || fifo_data[131]))
        write_buffer[fill_index]<=fifo_data[127:0];
    if (state==WRITE_PREP || (state==WRITE && !waitrequest))
        buffered_word<=write_buffer[buffer_read_addr];
end
assign writedata=buffered_word;
reg writing=0, ready=0, frame_bad=1, finishing=0, finish_ok=0;
reg [1:0] write_slot=0, ready_slot=0;
reg [9:0] ready_width=0, write_width=0;
reg [8:0] ready_height=0, write_height=0;
reg [16:0] write_count=0, expected_words=0;
reg [7:0] read_index=0, read_words=0;
reg bank=0, current_line_req=0, calculate_line=0;
reg [18:0] product=0, multiplicand=0;
reg [8:0] multiplier=0;
reg [3:0] multiply_bit=0;
wire [18:0] next_product=product+(multiplier[0] ? multiplicand : 19'd0);
(* altera_attribute="-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS", preserve, dont_merge *) reg pair_meta=0, pair_sync=0, line_meta=0, line_sync=0;
wire [8:0] origin_y=(9'd480-display_height)>>1;
wire [8:0] requested_y=line_payload[8:0];
wire [8:0] source_y=requested_y-origin_y;
wire image_line=display_valid && requested_y>=origin_y && source_y<display_height;
wire [1:0] free_slot=(!display_valid || display_slot!=0) && (!ready || ready_slot!=0) ? 2'd0 :
                     (!display_valid || display_slot!=1) && (!ready || ready_slot!=1) ? 2'd1 : 2'd2;
wire [4:0] tail_words={1'b0,fill_index}+(fifo_data[129:128]!=0 ? 5'd1 : 5'd0);
wire [16:0] total_words=write_count+17'(tail_words);
wire [10:0] line_pixels={1'b0,display_width}+{9'd0,next_product[1:0]}+11'd3;
wire [9:0] frame_width=SOURCE_WIDTH!=0 ? 10'(SOURCE_WIDTH) : fifo_data[9:0];
wire [8:0] frame_height=SOURCE_HEIGHT!=0 ? 9'(SOURCE_HEIGHT) : fifo_data[18:10];
function automatic [27:0] slot_address(input [1:0] slot);
    case (slot)
        0: slot_address=BASE_WORD;
        1: slot_address=BASE_WORD+SLOT_WORDS;
        2: slot_address=BASE_WORD+SLOT_WORDS*28'd2;
        3: slot_address=BASE_WORD+SLOT_WORDS*28'd3;
    endcase
endfunction
assign byteenable=16'hffff;
assign fifo_pop=state==POP && !fifo_empty;
always @(posedge clk) begin
    pair_meta<=pair_req; pair_sync<=pair_meta;
    line_meta<=line_req; line_sync<=line_meta;
    line_we<=0;
    case (state)
        IDLE: begin
            if (pair_sync!=pair_ack) begin
                if (ready) begin
                    display_slot<=ready_slot; display_width<=ready_width; display_height<=ready_height;
                    display_valid<=1; ready<=0;
                end else repeated<=repeated+1'b1;
                pair_ack<=pair_sync;
            end else if (!inhibit && line_sync!=line_ack) begin
                bank<=line_payload[9]; current_line_req<=line_sync;
                if (image_line) begin
                    product<=0; multiplicand<=19'(display_width); multiplier<=source_y;
                    multiply_bit<=0; calculate_line<=1; state<=CALCULATE;
                end else line_ack<=line_sync;
            end else if (!fifo_empty) state<=POP;
        end
        POP: if (!fifo_empty) state<=TOKEN;
        TOKEN: if (fifo_valid) begin
            if (fifo_data[133] && fifo_data[132]) begin
                if (writing) dropped<=dropped+1'b1;
                writing<=1; write_slot<=free_slot;
                write_width<=frame_width; write_height<=frame_height;
                frame_bad<=fifo_data[130] || inhibit; write_count<=0; fill_index<=0; finishing<=0;
                if (SOURCE_WIDTH!=0 && SOURCE_HEIGHT!=0) begin
                    expected_words<=17'((SOURCE_WIDTH*SOURCE_HEIGHT+3)/4); state<=IDLE;
                end else begin
                    product<=0; multiplicand<=19'(frame_width); multiplier<=frame_height;
                    multiply_bit<=0; calculate_line<=0; state<=CALCULATE;
                end
            end else if (fifo_data[133] && fifo_data[131]) begin
                finish_ok<=writing && !frame_bad && !fifo_data[130] && total_words==expected_words;
                finishing<=1;
                if (writing && !inhibit && tail_words!=0 && total_words<=expected_words && total_words<=17'd76800) begin
                    address<=slot_address(write_slot)+28'(write_count);
                    burstcount<=8'(tail_words); write_index<=0;
                    state<=WRITE_PREP;
                end else state<=FINISH;
            end else if (writing && !inhibit && write_count+17'(fill_index)<expected_words &&
                         write_count+17'(fill_index)<17'd76800) begin
                frame_bad<=frame_bad || fifo_data[130];
                fill_index<=fill_index+1'b1;
                if (fill_index==15) begin
                    address<=slot_address(write_slot)+28'(write_count);
                    burstcount<=16; write_index<=0; state<=WRITE_PREP;
                end else state<=IDLE;
            end else begin frame_bad<=1; state<=IDLE; end
        end
        WRITE_PREP: begin write<=1; state<=WRITE; end
        WRITE: if (!waitrequest) begin
            write_count<=write_count+1'b1;
            write_index<=write_index+1'b1;
            if (8'(write_index)==burstcount-1'b1) begin
                write<=0; state<=finishing ? FINISH : IDLE;
            end
        end
        // Nine memory clocks replace a variable multiplier on the address path.
        CALCULATE: begin
            product<=next_product; multiplicand<=multiplicand<<1; multiplier<=multiplier>>1;
            multiply_bit<=multiply_bit+1'b1;
            if (multiply_bit==8) begin
                if (calculate_line) begin
                    address<=slot_address(display_slot)+28'(next_product[18:2]);
                    read_words<=8'(line_pixels>>2); burstcount<=8'(line_pixels>>2);
                    read_index<=0; read<=1; state<=READ_CMD;
                end else begin expected_words<=17'((next_product+19'd3)>>2); state<=IDLE; end
            end
        end
        FINISH: begin
            if (finish_ok && !frame_bad && !inhibit) begin
                if (ready) dropped<=dropped+1'b1;
                ready<=1; ready_slot<=write_slot; ready_width<=write_width; ready_height<=write_height;
                published<=published+1'b1;
            end else dropped<=dropped+1'b1;
            writing<=0; finishing<=0; state<=IDLE;
        end
        READ_CMD: begin
            if (!waitrequest) begin read<=0; state<=READ_DATA; end
            if (readdatavalid) begin
                line_we<=1; line_addr<={bank,8'd0}; line_data<=readdata; read_index<=1;
                if (read_words==1) begin line_ack<=current_line_req; state<=IDLE; read<=0; end
            end
        end
        READ_DATA: if (readdatavalid) begin
            line_we<=1; line_addr<={bank,read_index}; line_data<=readdata;
            read_index<=read_index+1'b1;
            if (read_index==read_words-1'b1) begin line_ack<=current_line_req; state<=IDLE; end
        end
        default: state<=IDLE;
    endcase
    if (inhibit) frame_bad<=1;
end
endmodule
