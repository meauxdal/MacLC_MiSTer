`timescale 1ns/1ps
module tb_overlay;
    reg clk_sys = 0, clk_vid = 0, reset = 1;
    always #5 clk_sys = !clk_sys;
    always #7 clk_vid = !clk_vid;
    reg ce_pixel = 1, de = 0, vblank = 1;
    reg [199:0] status_sys = 0;
    wire [7:0] red_out, green_out, blue_out;
    iie_status_overlay dut (.clk_sys(clk_sys), .clk_vid(clk_vid), .reset(reset),
        .ce_pixel(ce_pixel), .de(de), .vblank(vblank), .status_sys(status_sys),
        .red_in(8'h20), .green_in(8'h30), .blue_in(8'h40), .*);
    localparam [199:0] FIRST = {4'd0, 4'h4, 16'hFB65, 16'hC07D, 8'hE0, 8'h04,
        16'hC07D, 16'd64, 32'd18052, 32'h1234, 32'hFEE0000C, 16'h0004};
    localparam [199:0] SECOND = {4'd0, 4'h5, 16'h2040, 16'hC0E8, 8'h28, 8'hA5,
        16'hC0E8, 16'd63, 32'd910, 32'h2345, 32'hFE000004, 16'hC0E8};
    reg [199:0] previous = 0;
    integer file_out = 0, ink = 0, background = 0, pixels = 0;
    reg [1023:0] output_path;
    task pixel;
        begin
            @(posedge clk_vid); #1;
            if (dut.snapshot != 0 && dut.snapshot != FIRST && dut.snapshot != SECOND)
                $fatal(1, "torn debug snapshot");
            if (!vblank && dut.snapshot != previous) $fatal(1, "snapshot changed during active video");
            previous = dut.snapshot;
            @(negedge clk_vid);
        end
    endtask
    task frame(input integer width, height, capture);
        integer row, col, old_x, old_y;
        reg in_panel;
        begin
            vblank = 1;
            de = 0;
            repeat (12) pixel();
            vblank = 0;
            for (row = 0; row < height; row = row + 1) begin
                de = 1;
                for (col = 0; col < width; col = col + 1) begin
                    pixel();
                    if (capture) begin
                        in_panel = col >= 8 && col < 296 && row >= height - 120 && row < height - 8;
                        if (!in_panel) begin
                            if ({red_out, green_out, blue_out} !== 24'h203040)
                                $fatal(1, "native pixels changed x=%0d y=%0d", col, row);
                            background = background + 1;
                        end else if ({red_out, green_out, blue_out} != 0) ink = ink + 1;
                        if (file_out) $fwrite(file_out, "%c%c%c", red_out, green_out, blue_out);
                        pixels = pixels + 1;
                    end
                    if (row == 100 && col == 100) status_sys = SECOND;
                end
                de = 0;
                repeat (3) pixel();
                old_x = int'(dut.x);
                old_y = int'(dut.y);
                ce_pixel = 0;
                pixel();
                if (int'(dut.x) != old_x || int'(dut.y) != old_y) $fatal(1, "position advanced without CE");
                ce_pixel = 1;
            end
        end
    endtask
    initial begin
        repeat (4) pixel();
        reset = 0;
        status_sys = FIRST;
        frame(512, 384, 0);
        frame(512, 384, 0);
        frame(512, 384, 0);
        if (dut.snapshot != SECOND) $fatal(1, "debug update missing");
        if (!$value$plusargs("output=%s", output_path)) $fatal(1, "output missing");
        file_out = $fopen(output_path, "wb");
        $fwrite(file_out, "P6\n512 384\n255\n");
        frame(512, 384, 1);
        $fclose(file_out);
        file_out = 0;
        if (pixels != 512 * 384 || background != 512 * 384 - 288 * 112 || ink < 1000)
            $fatal(1, "overlay coverage mismatch pixels=%0d background=%0d ink=%0d", pixels, background, ink);
        frame(640, 480, 0);
        frame(640, 480, 0);
        pixels = 0; background = 0; ink = 0;
        frame(640, 480, 1);
        if (pixels != 640 * 480 || background != 640 * 480 - 288 * 112 || ink < 1000)
            $fatal(1, "mode-change overlay mismatch");
        $display("PASS overlay snapshot, CE, native pixels, 384/480-line placement");
        $finish;
    end
endmodule
