`timescale 1ps/1ps
// Drives card_iwm_backend through a 16-bit hps_io block model and a CPU-paced
// read loop; nibble captures are decoded by check_iwm_backend.py.
module tb_iwm_backend;
    localparam integer IMAGE_BYTES = 1536 + 35 * 13 * 512;
    localparam integer CAPTURE = 7000;

    reg clk = 0;
    always #15385 clk = !clk;

    reg cold_reset = 1;
    reg [3:0] phases = 0;
    reg motor = 0, q6 = 0, q7 = 0, load = 0;
    reg [7:0] load_byte = 0;
    wire [22:0] control = {1'b0, load, load_byte, 5'd0, q7, q6, 1'b0, motor, phases};
    wire [11:0] drive;

    wire [31:0] sd_lba;
    wire sd_rd, sd_wr;
    reg sd_ack = 0, sd_buff_wr = 0, img_mounted = 0;
    reg [7:0] sd_buff_addr = 0;
    reg [15:0] sd_buff_dout = 0;
    wire [15:0] sd_buff_din;

    card_iwm_backend #(.HOLD_TICKS(143182)) dut (
        .clk(clk), .cold_reset(cold_reset), .control(control), .drive(drive),
        .write_protect(1'b0), .active(),
        .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_wr(sd_wr), .sd_ack(sd_ack),
        .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout), .sd_buff_din(sd_buff_din),
        .sd_buff_wr(sd_buff_wr), .img_mounted(img_mounted), .img_readonly(1'b0),
        .img_size(64'(IMAGE_BYTES))
    );

    reg [7:0] image [0:IMAGE_BYTES-1];
    integer blocks_read = 0, blocks_written = 0;

    // hps_io block transfer: one word per strobe, low byte even.
    task automatic serve;
        integer i, base;
        reg reading;
        begin
            base = sd_lba * 512;
            reading = sd_rd;
            repeat (40) @(posedge clk);
            sd_ack <= 1;
            for (i = 0; i < 256; i = i + 1) begin
                sd_buff_addr <= i;
                if (reading) begin
                    sd_buff_dout <= {image[base + 2 * i + 1], image[base + 2 * i]};
                    @(posedge clk) sd_buff_wr <= 1;
                    @(posedge clk) sd_buff_wr <= 0;
                    repeat (10) @(posedge clk);
                end else begin
                    repeat (12) @(posedge clk);
                    {image[base + 2 * i + 1], image[base + 2 * i]} = sd_buff_din;
                end
            end
            if (reading) blocks_read = blocks_read + 1;
            else blocks_written = blocks_written + 1;
            @(posedge clk) sd_ack <= 0;
            wait (!sd_rd && !sd_wr);
        end
    endtask
    always begin
        wait (sd_rd || sd_wr);
        serve;
    end

    // CPU read loop: poll every 1 us, take a byte when bit 7 is set, then
    // spend 12 us before the next poll, as RWTS does between nibbles.
    integer fd;
    task automatic capture(input integer count);
        integer n;
        begin
            n = 0;
            while (n < count) begin
                repeat (33) @(posedge clk);
                if (drive[7]) begin
                    $fwrite(fd, "%02x\n", drive[7:0]);
                    n = n + 1;
                    repeat (390) @(posedge clk);
                end
            end
        end
    endtask

    task automatic step(input [3:0] pattern);
        begin
            phases = pattern;
            repeat (32500 * 4) @(posedge clk);
        end
    endtask

    string image_path, out_path, write_path;
    integer wfd, wbyte, wclocks, wcount = 0, reads_before;
    initial begin
        if (!$value$plusargs("image=%s", image_path) || !$value$plusargs("out=%s", out_path) ||
            !$value$plusargs("write=%s", write_path))
            $fatal(1, "missing +image, +out or +write");
        wfd = $fopen(write_path, "r");
        $readmemh(image_path, image);
        fd = $fopen(out_path, "w");
        repeat (100) @(posedge clk);
        cold_reset = 0;
        repeat (100) @(posedge clk);
        img_mounted = 1;
        repeat (10) @(posedge clk);
        img_mounted = 0;
        wait (dut.mounted);
        if (drive[11]) $fatal(1, "drive enabled before motor on");
        motor = 1;
        repeat (10) @(posedge clk);
        if (!drive[11]) $fatal(1, "motor on did not enable the drive");
        $fwrite(fd, "T0\n");
        capture(CAPTURE);
        // Settle on track 0 with phase 0, then phases 1, 2, 3, 0: half a track each.
        step(4'b0001); step(4'b0010); step(4'b0100); step(4'b1000); step(4'b0001);
        phases = 0;
        repeat (32500 * 20) @(posedge clk);
        $fwrite(fd, "T2\n");
        capture(CAPTURE);
        motor = 0;
        repeat (32500 * 5) @(posedge clk);
        if (!drive[11]) $fatal(1, "enable dropped inside the shortened holdover");
        repeat (32500 * 6) @(posedge clk);
        if (drive[11]) $fatal(1, "enable held past the shortened holdover");

        // Reformat track 2 from the schedule, as RWTS writes: Q6 then Q7, one load per nibble.
        motor = 1;
        repeat (32500 * 2) @(posedge clk);
        q6 = 1;
        q7 = 1;
        while ($fscanf(wfd, "%h %d\n", wbyte, wclocks) == 2) begin
            load_byte = wbyte;
            @(posedge clk) load = 1;
            @(posedge clk) load = 0;
            repeat (wclocks - 2) @(posedge clk);
            wcount = wcount + 1;
        end
        q7 = 0;
        q6 = 0;
        motor = 0;
        reads_before = blocks_read;
        fork : flush
            wait (blocks_written >= 13) disable flush;
            begin repeat (32500 * 2000) @(posedge clk); $fatal(1, "dirty track not written back"); end
        join
        // Remount so the track comes back from the image, not the track RAM.
        repeat (32500) @(posedge clk);
        img_mounted = 1;
        repeat (10) @(posedge clk);
        img_mounted = 0;
        repeat (1000) @(posedge clk);
        wait (dut.mounted);
        motor = 1;
        $fwrite(fd, "W2\n");
        capture(CAPTURE);
        $fwrite(fd, "BLOCKS %0d %0d QTRACK %0d WRITTEN %0d RELOADED %0d\n", blocks_read, blocks_written,
                dut.qtrack, wcount, blocks_read - reads_before);
        $fclose(fd);
        $display("DONE");
        $finish;
    end
endmodule
