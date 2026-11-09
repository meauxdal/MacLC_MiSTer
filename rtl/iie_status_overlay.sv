module iie_status_overlay (
    input wire clk_sys, clk_vid, reset,
    input wire enable_sys,
    input wire ce_pixel, de, vblank,
    input wire [271:0] status_sys,
    input wire [15:0] pvia_sys,  // {PseudoVIA $01 ram_cfg, $10 video config}, shown on row 9 as R and D
    input wire [127:0] drive_sys, // card_iwm_backend debug, rows 10-12
    input wire [7:0] red_in, green_in, blue_in,
    output wire [7:0] red_out, green_out, blue_out
);
    reg request = 0, acknowledge = 0;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *) reg [1:0] enable_sync = 2'b11;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *) reg [1:0] request_sync = 0, acknowledge_sync = 0;
    reg [415:0] held = 0, snapshot = 0;
    reg vblank_d = 0, de_d = 0;
    reg [10:0] x = 0, y = 0, active_lines = 384;
    always @(posedge clk_sys) begin
        request_sync <= {request_sync[0], request};
        if (reset) begin
            held <= 0;
            acknowledge <= 0;
            request_sync <= 0;
        end else if (request_sync[1] != acknowledge) begin
            held <= {drive_sys, pvia_sys, status_sys};
            acknowledge <= request_sync[1];
        end
    end
    always @(posedge clk_vid) begin
        enable_sync <= reset ? 2'b11 : {enable_sync[0], enable_sys};
        acknowledge_sync <= {acknowledge_sync[0], acknowledge};
        if (reset) begin
            request <= 0;
            acknowledge_sync <= 0;
            snapshot <= 0;
            vblank_d <= 0;
            de_d <= 0;
            x <= 0;
            y <= 0;
            active_lines <= 384;
        end else if (ce_pixel) begin
            vblank_d <= vblank;
            de_d <= de;
            if (vblank && !vblank_d && acknowledge_sync[1] == request) begin
                snapshot <= held;
                request <= !request;
            end
            if (vblank && !vblank_d && y >= 128) active_lines <= y;
            if (vblank) begin
                x <= 0;
                y <= 0;
            end else begin
                if (de) x <= de_d ? x + 11'd1 : 11'd0;
                else x <= 0;
                if (!de && de_d) y <= y + 11'd1;
            end
        end
    end
    function automatic [7:0] hex_char(input [3:0] value);
        hex_char = value < 10 ? 8'h30 + {4'b0, value} : 8'h41 + {4'b0, value} - 8'd10;
    endfunction
    function automatic [34:0] glyph(input [7:0] ch);
        case (ch)
            "0": glyph = 35'b01110_10001_10011_10101_11001_10001_01110;
            "1": glyph = 35'b00100_01100_00100_00100_00100_00100_01110;
            "2": glyph = 35'b01110_10001_00001_00010_00100_01000_11111;
            "3": glyph = 35'b11110_00001_00001_01110_00001_00001_11110;
            "4": glyph = 35'b00010_00110_01010_10010_11111_00010_00010;
            "5": glyph = 35'b11111_10000_10000_11110_00001_00001_11110;
            "6": glyph = 35'b01110_10000_10000_11110_10001_10001_01110;
            "7": glyph = 35'b11111_00001_00010_00100_01000_01000_01000;
            "8": glyph = 35'b01110_10001_10001_01110_10001_10001_01110;
            "9": glyph = 35'b01110_10001_10001_01111_00001_00001_01110;
            "A": glyph = 35'b01110_10001_10001_11111_10001_10001_10001;
            "B": glyph = 35'b11110_10001_10001_11110_10001_10001_11110;
            "C": glyph = 35'b01111_10000_10000_10000_10000_10000_01111;
            "D": glyph = 35'b11110_10001_10001_10001_10001_10001_11110;
            "E": glyph = 35'b11111_10000_10000_11110_10000_10000_11111;
            "F": glyph = 35'b11111_10000_10000_11110_10000_10000_10000;
            "G": glyph = 35'b01111_10000_10000_10111_10001_10001_01111;
            "I": glyph = 35'b01110_00100_00100_00100_00100_00100_01110;
            "K": glyph = 35'b10001_10010_10100_11000_10100_10010_10001;
            "L": glyph = 35'b10000_10000_10000_10000_10000_10000_11111;
            "M": glyph = 35'b10001_11011_10101_10101_10001_10001_10001;
            "N": glyph = 35'b10001_11001_10101_10011_10001_10001_10001;
            "O": glyph = 35'b01110_10001_10001_10001_10001_10001_01110;
            "P": glyph = 35'b11110_10001_10001_11110_10000_10000_10000;
            "Q": glyph = 35'b01110_10001_10001_10001_10101_10010_01101;
            "R": glyph = 35'b11110_10001_10001_11110_10100_10010_10001;
            "S": glyph = 35'b01111_10000_10000_01110_00001_00001_11110;
            "T": glyph = 35'b11111_00100_00100_00100_00100_00100_00100;
            "U": glyph = 35'b10001_10001_10001_10001_10001_10001_01110;
            "W": glyph = 35'b10001_10001_10001_10101_10101_10101_01010;
            default: glyph = 0;
        endcase
    endfunction
    function automatic [7:0] text_char(input integer row, col, input [415:0] data);
        reg [191:0] label;
        begin
            case (row)
                0: label = "IIE TRIAL               ";
                1: label = "PC 0000 FLAGS 00        ";
                2: label = "CAP 0000 S00 D00        ";
                3: label = "BUS 0000 CAP N 0000     ";
                4: label = "CPU N 00000000          ";
                5: label = "PDS N 00000000          ";
                6: label = "PDS 00000000 0000       ";
                7: label = "START 00 O0 N0 F0       ";
                8: label = "CMD 0000 MASK 00 ST 00  ";
                9: label = "CAP 0000 S00 R00 D00    ";
                10: label = "D1 M0 S0 T00 R00 K00 L00";
                11: label = "D2 M0 S0 T00 R00 K00 L00";
                12: label = "IWM E0 P0 Q0 N0000 F0000";
                default: label = 0;
            endcase
            text_char = label[191 - col * 8 -: 8];
            if (row == 1 && col >= 3 && col <= 6) text_char = hex_char(data[191 - (col - 3) * 4 -: 4]);
            if (row == 1 && col == 14) text_char = hex_char(data[199:196]);
            if (row == 1 && col == 15) text_char = hex_char(data[195:192]);
            if (row == 2 && col >= 4 && col <= 7) text_char = hex_char(data[175 - (col - 4) * 4 -: 4]);
            if (row == 2 && col >= 10 && col <= 11) text_char = hex_char(data[159 - (col - 10) * 4 -: 4]);
            if (row == 2 && col >= 14 && col <= 15) text_char = hex_char(data[151 - (col - 14) * 4 -: 4]);
            if (row == 3 && col >= 4 && col <= 7) text_char = hex_char(data[143 - (col - 4) * 4 -: 4]);
            if (row == 3 && col >= 15 && col <= 18) text_char = hex_char(data[127 - (col - 15) * 4 -: 4]);
            if (row >= 4 && row <= 5 && col >= 6 && col <= 13)
                text_char = hex_char(data[143 - (row - 3) * 32 - (col - 6) * 4 -: 4]);
            if (row == 6 && col >= 4 && col <= 11) text_char = hex_char(data[47 - (col - 4) * 4 -: 4]);
            if (row == 6 && col >= 13 && col <= 16) text_char = hex_char(data[15 - (col - 13) * 4 -: 4]);
            if (row == 7 && col >= 6 && col <= 7) text_char = hex_char(data[215 - (col - 6) * 4 -: 4]);
            if (row == 7 && col == 10) text_char = hex_char({3'b0, data[207]});
            if (row == 7 && col == 13) text_char = hex_char({1'b0, data[206:204]});
            if (row == 7 && col == 16) text_char = hex_char(data[203:200]);
            if (row == 8 && col >= 4 && col <= 7) text_char = hex_char(data[271 - (col - 4) * 4 -: 4]);
            if (row == 8 && col >= 14 && col <= 15) text_char = hex_char(data[255 - (col - 14) * 4 -: 4]);
            if (row == 8 && col >= 20 && col <= 21) text_char = hex_char(data[247 - (col - 20) * 4 -: 4]);
            if (row == 9 && col >= 4 && col <= 7) text_char = hex_char(data[239 - (col - 4) * 4 -: 4]);
            if (row == 9 && col >= 10 && col <= 11) text_char = hex_char(data[223 - (col - 10) * 4 -: 4]);
            if (row == 9 && col >= 14 && col <= 15) text_char = hex_char(data[287 - (col - 14) * 4 -: 4]);
            if (row == 9 && col >= 18 && col <= 19) text_char = hex_char(data[279 - (col - 18) * 4 -: 4]);
            // Rows 10-11: drive 1 at data[327:288], drive 2 at data[367:328].
            if (row >= 10 && row <= 11) begin
                if (col == 4) text_char = hex_char(data[327 + (row - 10) * 40 -: 4]);
                if (col == 7) text_char = hex_char(data[323 + (row - 10) * 40 -: 4]);
                if (col >= 10 && col <= 11)
                    text_char = hex_char(data[319 + (row - 10) * 40 - (col - 10) * 4 -: 4]);
                if (col >= 14 && col <= 15)
                    text_char = hex_char(data[311 + (row - 10) * 40 - (col - 14) * 4 -: 4]);
                if (col >= 18 && col <= 19)
                    text_char = hex_char(data[303 + (row - 10) * 40 - (col - 18) * 4 -: 4]);
                if (col >= 22 && col <= 23)
                    text_char = hex_char(data[295 + (row - 10) * 40 - (col - 22) * 4 -: 4]);
            end
            // Row 12: sequencer at data[411:368].
            if (row == 12 && col == 5) text_char = hex_char(data[411:408]);
            if (row == 12 && col == 8) text_char = hex_char(data[407:404]);
            if (row == 12 && col == 11) text_char = hex_char(data[403:400]);
            if (row == 12 && col >= 14 && col <= 17) text_char = hex_char(data[399 - (col - 14) * 4 -: 4]);
            if (row == 12 && col >= 20 && col <= 23) text_char = hex_char(data[383 - (col - 20) * 4 -: 4]);
        end
    endfunction
    // Character-cell position as counters that track x and y, so the pixel
    // path holds no divider. A cell is 12 pixels wide and starts at x = 8, so
    // a line starts at sub_x 4 of cell -1 (col_q 63). The glyph of the next
    // cell is fetched into bitmap_q on the last pixel of the current one,
    // which leaves the text mux a whole clock and the pixel path only a bit
    // select.
    reg [3:0] sub_x = 4'd4;
    reg [5:0] col_q = 6'd63;
    reg signed [11:0] py_q = 0;
    reg [34:0] bitmap_q = 0;
    wire signed [11:0] panel_top = $signed({1'b0, active_lines}) - 12'sd216;
    wire [5:0] col_next = col_q + 6'd1;
    always @(posedge clk_vid) begin
        if (reset) begin
            sub_x <= 4'd4;
            col_q <= 6'd63;
            py_q <= 0;
            bitmap_q <= 0;
        end else if (ce_pixel) begin
            py_q <= $signed({1'b0, y}) - panel_top;
            if (sub_x == 4'd11) bitmap_q <= glyph(text_char(int'($signed(py_q[11:4])), int'(col_next), snapshot));
            if (!vblank && de && de_d) begin
                sub_x <= sub_x == 4'd11 ? 4'd0 : sub_x + 4'd1;
                if (sub_x == 4'd11) col_q <= col_next;
            end else begin
                sub_x <= 4'd4;
                col_q <= 6'd63;
            end
        end
    end
    wire [3:0] row = py_q[7:4];
    wire [2:0] gx = sub_x[3:1];
    wire [2:0] gy = py_q[3:1];
    wire panel = enable_sync[1] && de && col_q < 6'd24 && py_q >= 0 && py_q < 12'sd208;
    wire ink = panel && gx < 3'd5 && gy < 3'd7 && bitmap_q[6'd34 - {3'b0, gy} * 6'd5 - {3'b0, gx}];
    assign red_out = panel ? (ink && (row != 0 || snapshot[192]) ? 8'hFF : 8'h00) : red_in;
    assign green_out = panel ? (ink && (row != 0 || !snapshot[192]) ? 8'hFF : 8'h00) : green_in;
    assign blue_out = panel ? (ink && row != 0 ? 8'hFF : 8'h00) : blue_in;
endmodule
