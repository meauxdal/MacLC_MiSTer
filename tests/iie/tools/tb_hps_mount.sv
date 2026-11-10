`timescale 1ps/1ps
// Mounts a WOZ image on IIe drive 1 through the real sys/hps_io.sv. The HPS
// side copies sys_top's io_clk/rack/io_ack handshake and Main's command order:
// 0x1D size, 0x1C mount, then 0x16 status polls answered with 0x0X17 sector
// reads. Prints the controller's progress once per simulated millisecond.
//   +image=<woz>  +ms=<run time>  +hps_ns=<HPS access time, default 60>
module tb_hps_mount;
    localparam VDNUM = 9;
    localparam SLOT = 7;                  // VD_IIE_DRIVE1

    reg clk = 0;
    always #15385 clk = !clk;             // 32.5 MHz clk_sys

    // ---- sys_top HPS bridge copy ----
    reg [31:0] gp_out = 0;
    reg [31:0] gp_outd = 0, gp_outr = 0;
    always @(posedge clk) begin
        gp_outd <= gp_out;
        gp_outr <= gp_outd;
    end
    wire [15:0] io_din = gp_outr[15:0];
    wire io_clk = gp_outr[17];
    wire io_ss0 = gp_outr[18];
    wire io_ss1 = gp_outr[19];
    wire io_ss2 = gp_outr[20];
    wire io_uio = ~io_ss1 & io_ss2;
    reg io_ack = 0, rack = 0;
    wire io_strobe = ~rack & io_clk;
    always @(posedge clk) begin
        rack <= io_clk;
        io_ack <= rack;
    end

    wire [45:0] HPS_BUS;
    assign HPS_BUS[31:16] = io_din;
    assign HPS_BUS[33] = io_strobe;
    assign HPS_BUS[34] = io_uio;
    assign HPS_BUS[35] = 1'b0;
    assign HPS_BUS[45:38] = 0;
    wire [15:0] io_dout = HPS_BUS[15:0];
    wire [35:0] EXT_BUS;
    assign EXT_BUS[32] = 1'b0;
    assign EXT_BUS[15:0] = 0;
    wire [21:0] gamma_bus;

    // ---- core side, wired as in MacLC.sv ----
    wire [31:0] sd_lba[VDNUM];
    wire [VDNUM-1:0] sd_rd, sd_wr, sd_ack, img_mounted;
    wire [12:0] sd_buff_addr;
    wire [15:0] sd_buff_dout;
    wire [15:0] sd_buff_din[VDNUM];
    wire sd_buff_wr, img_readonly;
    wire [63:0] img_size;
    wire [5:0] sd_blk_cnt[VDNUM];

    genvar g;
    generate
        for (g = 0; g < VDNUM; g = g + 1) begin : idle_slots
            assign sd_blk_cnt[g] = 0;
            if (g != SLOT && g != SLOT + 1) begin : other
                assign sd_lba[g] = 0;
                assign sd_buff_din[g] = 0;
                assign sd_rd[g] = 0;
                assign sd_wr[g] = 0;
            end
        end
    endgenerate

    hps_io #(.CONF_STR("MacLC;;"), .VDNUM(VDNUM), .WIDE(1)) hps_io (
        .clk_sys(clk), .HPS_BUS(HPS_BUS), .EXT_BUS(EXT_BUS), .gamma_bus(gamma_bus),
        .joystick_0_rumble(16'd0), .joystick_1_rumble(16'd0), .joystick_2_rumble(16'd0),
        .joystick_3_rumble(16'd0), .joystick_4_rumble(16'd0), .joystick_5_rumble(16'd0),
        .ps2_kbd_clk_in(1'b1), .ps2_kbd_data_in(1'b1), .ps2_kbd_led_status(3'd0),
        .ps2_kbd_led_use(3'd0), .ps2_mouse_clk_in(1'b1), .ps2_mouse_data_in(1'b1),
        .video_rotated(1'b0), .new_vmode(1'b0),
        .status_in(128'd0), .status_set(1'b0), .status_menumask(16'd0),
        .info_req(1'b0), .info(8'd0),
        .img_mounted(img_mounted), .img_readonly(img_readonly), .img_size(img_size),
        .sd_lba(sd_lba), .sd_blk_cnt(sd_blk_cnt), .sd_rd(sd_rd), .sd_wr(sd_wr),
        .sd_ack(sd_ack), .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout),
        .sd_buff_din(sd_buff_din), .sd_buff_wr(sd_buff_wr),
        .ioctl_upload_req(1'b0), .ioctl_upload_index(8'd0), .ioctl_din(16'd0),
        .ioctl_wait(1'b0)
    );

    reg cold_reset = 1;
    wire [11:0] drive;
    wire [127:0] debug;
    card_iwm_backend iie_drive (
        .clk(clk), .cold_reset(cold_reset), .control(23'd0), .drive(drive),
        .write_protect(1'b1), .active(), .debug(debug),
        .sd_lba({sd_lba[SLOT + 1], sd_lba[SLOT]}),
        .sd_rd(sd_rd[SLOT + 1:SLOT]), .sd_wr(sd_wr[SLOT + 1:SLOT]),
        .sd_ack(sd_ack[SLOT + 1:SLOT]), .sd_buff_addr(sd_buff_addr[7:0]),
        .sd_buff_dout(sd_buff_dout),
        .sd_buff_din({sd_buff_din[SLOT + 1], sd_buff_din[SLOT]}),
        .sd_buff_wr(sd_buff_wr), .img_mounted(img_mounted[SLOT + 1:SLOT]),
        .img_readonly(img_readonly), .img_size(img_size)
    );

    // ---- image ----
    reg [7:0] image [0:4*1024*1024-1];
    integer image_bytes = 0;
    integer hps_ps = 60000;

    // ---- HPS (Main) model ----
    task automatic hps_wait;
        #(hps_ps);
    endtask

    task automatic enable_io;
        begin gp_out[20:18] = 3'b100; hps_wait(); end
    endtask
    task automatic disable_io;
        begin gp_out[20:18] = 3'b000; hps_wait(); end
    endtask

    // One spi_w: present the word with io_clk high, wait for io_ack, read
    // io_dout, drop io_clk, wait for io_ack low.
    task automatic spi_w(input [15:0] d, output [15:0] q);
        begin
            gp_out[15:0] = d;
            gp_out[17] = 1;
            hps_wait();
            while (!io_ack) hps_wait();
            q = io_dout;
            gp_out[17] = 0;
            hps_wait();
            while (io_ack) hps_wait();
        end
    endtask

    integer reads = 0, polls = 0, unserved = 0;
    reg [15:0] q;

    task automatic mount;
        begin
            enable_io();
            spi_w(16'h001D, q);
            spi_w(image_bytes[15:0], q);
            spi_w(image_bytes[31:16], q);
            spi_w(16'd0, q);
            spi_w(16'd0, q);
            disable_io();
            enable_io();
            spi_w(16'h001C, q);
            spi_w(16'd1 << SLOT, q);
            disable_io();
        end
    endtask

    task automatic poll_and_serve;
        reg [15:0] st, lo, hi;
        reg [3:0] n;
        reg [31:0] lba;
        integer i, base;
        begin
            enable_io();
            spi_w(16'h0016, st);
            spi_w(16'd0, q);
            spi_w(16'd0, lo);
            spi_w(16'd0, hi);
            disable_io();
            polls = polls + 1;
            n = st[5:2];
            lba = {hi, lo};
            if (st[15] && st[0]) begin
                if (n != SLOT) unserved = unserved + 1;
                else begin
                    base = lba * 512;
                    enable_io();
                    spi_w({4'h0, n, 8'h17}, q);
                    for (i = 0; i < 256; i = i + 1) begin
                        if (base + 2 * i + 1 < image_bytes)
                            spi_w({image[base + 2 * i + 1], image[base + 2 * i]}, q);
                        else spi_w(16'd0, q);
                    end
                    disable_io();
                    reads = reads + 1;
                end
            end
        end
    endtask

    // ---- monitor ----
    `define CTRL iie_drive.unit[0].disk.controller
    integer ms = 0, run_ms = 40;
    always begin
        #1000000000;
        ms = ms + 1;
        $display("t=%0dms reads=%0d polls=%0d state=%0d mount=%0d woz_valid=%0d scan_failed=%0d scan_blocks=%0d have=%0d%0d%0d ver=%0d hdr_pos=%0d chunk_id=%h lba=%0d",
                 ms, reads, polls, `CTRL.state, iie_drive.unit[0].disk.mount,
                 `CTRL.woz_valid, `CTRL.scan_failed, `CTRL.scan_blocks,
                 `CTRL.have_info, `CTRL.have_tmap, `CTRL.have_trks,
                 `CTRL.info_version, `CTRL.hdr_pos, `CTRL.chunk_id, sd_lba[SLOT]);
        if (ms >= run_ms) begin
            $display("scan_debug=%h", iie_drive.scan_debug);
            $display("DONE disk_mounted=%0d", `CTRL.disk_mounted);
            $finish;
        end
    end

    // First bytes the parser takes, to compare with the file.
    integer seen = 0;
    always @(posedge clk)
        if (`CTRL.sd_ack && `CTRL.sd_buff_wr && `CTRL.state == 2 && seen < 24) begin
            $display("parser byte %0d = %02h (gate=%0d)", seen, `CTRL.sd_buff_dout,
                     `CTRL.transfer_active || (!`CTRL.old_ack && `CTRL.sd_ack));
            seen = seen + 1;
        end

    initial begin
        string path;
        integer fd, c, ns;
        if (!$value$plusargs("image=%s", path)) $fatal(1, "+image required");
        if ($value$plusargs("ms=%d", run_ms)) ;
        if ($value$plusargs("hps_ns=%d", ns)) hps_ps = ns * 1000;
        fd = $fopen(path, "rb");
        if (fd == 0) $fatal(1, "cannot open %s", path);
        c = $fgetc(fd);
        while (c != -1) begin
            image[image_bytes] = c;
            image_bytes = image_bytes + 1;
            c = $fgetc(fd);
        end
        $fclose(fd);
        $display("image %0d bytes, first %02h%02h%02h%02h", image_bytes,
                 image[0], image[1], image[2], image[3]);
        repeat (20) @(posedge clk);
        cold_reset = 0;
        repeat (100) @(posedge clk);
        mount();
        forever poll_and_serve();
    end
endmodule
