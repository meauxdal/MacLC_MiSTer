`timescale 1ns/1ps
module tb_card_trap_decode;
    reg valid, write, aux;
    reg [15:0] address;
    reg text_active, text_page2, hires_active, hires_page2;
    reg col80, full_graphics, double_hires, motor;
    wire display_trap, io_trap;
    reg [3:0] expected [0:65535];
    reg [1023:0] image;
    reg [7:0] mode;
    integer a, direction, bank, count, display_count, io_count;
    reg expected_display, expected_io;

    card_trap_decode dut (.*);

    initial begin
        if (!$value$plusargs("image=%s", image) || !$value$plusargs("mode=%h", mode))
            $fatal(1, "missing image or mode");
        $readmemh(image, expected);
        {text_active, text_page2, hires_active, hires_page2,
         col80, full_graphics, double_hires, motor} = mode;
        count = 0;
        display_count = 0;
        io_count = 0;
        valid = 1;
        for (bank = 0; bank < 2; bank = bank + 1) begin
            aux = bank != 0;
            for (direction = 0; direction < 2; direction = direction + 1) begin
                write = direction != 0;
                for (a = 0; a < 65536; a = a + 1) begin
                    address = a[15:0];
                    #1;
                    expected_display = write && expected[a][bank];
                    expected_io = expected[a][2 + direction];
                    if (display_trap !== expected_display || io_trap !== expected_io)
                        $fatal(1, "mode=%h address=%h write=%b aux=%b display=%b/%b io=%b/%b",
                               mode, address, write, aux, display_trap, expected_display,
                               io_trap, expected_io);
                    display_count = display_count + (display_trap ? 1 : 0);
                    io_count = io_count + (io_trap ? 1 : 0);
                    count = count + 1;
                    valid = 0;
                    #1;
                    if (display_trap !== 1'b0 || io_trap !== 1'b0)
                        $fatal(1, "invalid transaction trapped");
                    valid = 1;
                end
            end
        end
        $display("PASS mode=%h accesses=%0d invalid=%0d display=%0d io=%0d",
                 mode, count, count, display_count, io_count);
        $finish;
    end
endmodule
