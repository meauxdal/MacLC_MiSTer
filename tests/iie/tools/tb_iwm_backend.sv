`timescale 1ps/1ps
// Drives card_iwm_backend through a 16-bit hps_io block model and a CPU-paced
// read loop; nibble captures are decoded by check_iwm_backend.py.
// +drive2 runs the sequence on drive 2 with both drives mounted, then checks
// that drive 1's image, head and track RAM were left alone.
module tb_iwm_backend;
    localparam integer IMAGE_BYTES = 1536 + 35 * 13 * 512;
    localparam integer CAPTURE = 7500;

    reg clk = 0;
    always #15385 clk = !clk;

    reg cold_reset = 1;
    reg [3:0] phases = 0;
    reg motor = 0, q6 = 0, q7 = 0, load = 0, select = 0;
    reg [7:0] load_byte = 0;
    wire [22:0] control = {1'b0, load, load_byte, 5'd0, q7, q6, select, motor, phases};
    wire [11:0] drive;

    wire [63:0] sd_lba;
    wire [1:0] sd_rd, sd_wr;
    reg [1:0] sd_ack = 0, img_mounted = 0;
    reg sd_buff_wr = 0;
    reg [7:0] sd_buff_addr = 0;
    reg [15:0] sd_buff_dout = 0;
    wire [31:0] sd_buff_din;

    card_iwm_backend #(.HOLD_TICKS(143182)) dut (
        .clk(clk), .cold_reset(cold_reset), .control(control), .drive(drive),
        .write_protect(1'b0), .active(),
        .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_wr(sd_wr), .sd_ack(sd_ack),
        .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout), .sd_buff_din(sd_buff_din),
        .sd_buff_wr(sd_buff_wr), .img_mounted(img_mounted), .img_readonly(1'b0),
        .img_size(64'(IMAGE_BYTES))
    );

    // One image per hps_io slot; the active drive's slot is `slot`.
    reg [7:0] image0 [0:IMAGE_BYTES-1];
    reg [7:0] image1 [0:IMAGE_BYTES-1];
    integer reads [0:1], writes [0:1];
    integer slot = 0;
    initial begin
        reads[0] = 0; reads[1] = 0; writes[0] = 0; writes[1] = 0;
    end

    // hps_io block transfer: one word per strobe, low byte even. The buffer
    // is shared, so one slot is served at a time.
    task automatic serve(input integer k);
        integer i, base;
        reg reading;
        reg [15:0] word;
        begin
            base = sd_lba[32 * k +: 32] * 512;
            reading = sd_rd[k];
            repeat (40) @(posedge clk);
            sd_ack[k] <= 1;
            for (i = 0; i < 256; i = i + 1) begin
                sd_buff_addr <= i;
                if (reading) begin
                    if (k == 0) sd_buff_dout <= {image0[base + 2 * i + 1], image0[base + 2 * i]};
                    else sd_buff_dout <= {image1[base + 2 * i + 1], image1[base + 2 * i]};
                    @(posedge clk) sd_buff_wr <= 1;
                    @(posedge clk) sd_buff_wr <= 0;
                    repeat (10) @(posedge clk);
                end else begin
                    repeat (12) @(posedge clk);
                    word = sd_buff_din[16 * k +: 16];
                    if (k == 0) {image0[base + 2 * i + 1], image0[base + 2 * i]} = word;
                    else {image1[base + 2 * i + 1], image1[base + 2 * i]} = word;
                end
            end
            if (reading) reads[k] = reads[k] + 1;
            else writes[k] = writes[k] + 1;
            @(posedge clk) sd_ack[k] <= 0;
            wait (!sd_rd[k] && !sd_wr[k]);
        end
    endtask
    always begin
        wait (sd_rd != 0 || sd_wr != 0);
        serve((sd_rd[0] || sd_wr[0]) ? 0 : 1);
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

    task automatic mount(input integer k);
        begin
            img_mounted[k] = 1;
            repeat (10) @(posedge clk);
            img_mounted[k] = 0;
        end
    endtask

    string image_path, out_path, write_path;
    integer wfd, wbyte, wclocks, wcount = 0, reads_before;
    reg drive2;
    initial begin
        if (!$value$plusargs("image=%s", image_path) || !$value$plusargs("out=%s", out_path) ||
            !$value$plusargs("write=%s", write_path))
            $fatal(1, "missing +image, +out or +write");
        drive2 = $test$plusargs("drive2");
        slot = drive2 ? 1 : 0;
        select = drive2;
        wfd = $fopen(write_path, "r");
        $readmemh(image_path, image0);
        $readmemh(image_path, image1);
        fd = $fopen(out_path, "w");
        repeat (100) @(posedge clk);
        cold_reset = 0;
        repeat (100) @(posedge clk);
        // In drive 2 mode drive 1 holds the same image, mounted first.
        if (drive2) begin
            mount(0);
            repeat (1000) @(posedge clk);
        end
        mount(slot);
        wait (dut.mounted);
        if (drive2 && !dut.mounted_n[0]) $fatal(1, "drive 1 not mounted");
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
        reads_before = reads[slot];
        fork : flush
            wait (writes[slot] >= 13) disable flush;
            begin repeat (32500 * 2000) @(posedge clk); $fatal(1, "dirty track not written back"); end
        join
        // Remount so the track comes back from the image, not the track RAM.
        repeat (32500) @(posedge clk);
        mount(slot);
        repeat (1000) @(posedge clk);
        wait (dut.mounted);
        motor = 1;
        $fwrite(fd, "W2\n");
        capture(CAPTURE);
        $fwrite(fd, "BLOCKS %0d %0d QTRACK %0d WRITTEN %0d RELOADED %0d\n", reads[slot], writes[slot],
                dut.qtrack, wcount, reads[slot] - reads_before);

        if (drive2) begin
            // Drive 1: no writes, head still on track 0, and its track RAM
            // still reads track 0.
            if (writes[0] != 0) $fatal(1, "drive 1 wrote %0d blocks", writes[0]);
            if (dut.qtrack_n[0] != 0) $fatal(1, "drive 1 head moved to qtrack %0d", dut.qtrack_n[0]);
            motor = 0;
            repeat (32500 * 12) @(posedge clk);
            select = 0;
            reads_before = reads[0];
            motor = 1;
            repeat (32500 * 2) @(posedge clk);
            if (!drive[11]) $fatal(1, "motor on did not enable drive 1");
            $fwrite(fd, "O0\n");
            capture(CAPTURE);
            $fwrite(fd, "OTHER %0d %0d QTRACK %0d RELOADED %0d\n", reads[0], writes[0],
                    dut.qtrack_n[0], reads[0] - reads_before);
        end
        $fclose(fd);
        $display("DONE");
        $finish;
    end
endmodule
