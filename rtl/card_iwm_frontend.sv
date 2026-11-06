// IWM register front end. Drive timing and serial data belong to the backend.
module card_iwm_frontend (
    input wire clk,
    input wire reset,
    input wire complete,
    input wire selected,
    input wire [3:0] address,
    input wire write,
    input wire [7:0] write_data,
    input wire [7:0] drive_data,
    input wire drive_sense,
    input wire drive_enabled,
    input wire write_busy,
    input wire write_underrun,
    output reg [7:0] read_data,
    output reg [3:0] phases,
    output reg motor,
    output reg drive_select,
    output reg q6,
    output reg q7,
    output reg [4:0] mode,
    output wire data_read,
    output wire data_write,
    output wire [7:0] data_out
);
    wire access = selected && !reset;
    wire q6_next = access && address[3:1] == 3'b110 ? address[0] : q6;
    wire q7_next = access && address[3:1] == 3'b111 ? address[0] : q7;
    wire [1:0] reg_select = {q7_next, q6_next};
    assign data_read = access && complete && !write && motor && reg_select == 2'b00;
    assign data_write = access && complete && write && motor && reg_select == 2'b11;
    assign data_out = write_data;

    always @* begin
        case (reg_select)
            2'b00: read_data = drive_enabled ? drive_data : 8'hFF;
            2'b01: read_data = {drive_sense, 1'b0, drive_enabled, mode};
            2'b10: read_data = {!write_busy, !write_underrun, 6'b0};
            2'b11: read_data = 0;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            phases <= 0;
            motor <= 0;
            drive_select <= 0;
            q6 <= 0;
            q7 <= 0;
            mode <= 0;
        end else if (selected && complete) begin
            if (!address[3]) phases[address[2:1]] <= address[0];
            else begin
                case (address[2:1])
                    2'b00: motor <= address[0];
                    2'b01: drive_select <= address[0];
                    2'b10: q6 <= address[0];
                    2'b11: q7 <= address[0];
                endcase
            end
            if (write && reg_select == 2'b11 && !motor) mode <= write_data[4:0];
        end
    end
endmodule
