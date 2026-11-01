`timescale 1ns/1ps
module tb_loader_bounds;
    parameter [63:0] TEST_WORDS = 64'h200;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1, img_mounted = 0, header = 0;
    reg [63:0] img_size = 0;
    reg [23:0] base_addr = 24'h600000;
    wire [31:0] sd_lba;
    wire sd_rd, wr_req, loading, done, readonly, raw_img, is_dc42, media_ds;
    wire [23:0] wr_addr;
    wire [15:0] wr_data, hdr_data;
    wire [63:0] size;
    wire [7:0] dc42_fmt;
    reg sd_ack = 0, sd_buff_wr = 0, wr_ack = 0;
    reg [12:0] sd_buff_addr = 0;
    reg [15:0] sd_buff_dout = 0;
    floppy_loader #(.REGION_WORDS(TEST_WORDS)) dut (
        .clk_sys(clk), .reset(reset), .img_mounted(img_mounted), .img_size(img_size),
        .img_readonly(1'b0), .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_ack(sd_ack),
        .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout), .sd_buff_wr(sd_buff_wr),
        .base_addr(base_addr), .wr_addr(wr_addr), .wr_data(wr_data), .wr_req(wr_req),
        .wr_ack(wr_ack), .loading(loading), .done(done), .size(size), .readonly(readonly),
        .raw_img(raw_img), .is_dc42(is_dc42), .hdr_addr(6'b0), .hdr_data(hdr_data),
        .media_ds(media_ds), .dc42_fmt(dc42_fmt)
    );
    integer ticks = 0, writes = 0, sectors = 0, cases = 0;
    reg [23:0] expected_base = 0;
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 100000) $fatal(1, "loader bounds watchdog");
        if (reset) begin wr_ack <= 0; writes = 0; end
        else if (wr_req && !wr_ack) begin
            if ({40'd0, wr_addr} < {40'd0, expected_base} ||
                {40'd0, wr_addr} >= {40'd0, expected_base} + TEST_WORDS ||
                wr_addr !== expected_base + 24'(writes))
                $fatal(1, "loader escaped or aliased reservation: %h write=%0d", wr_addr, writes);
            writes = writes + 1;
            wr_ack <= 1;
        end else if (!wr_req) wr_ack <= 0;
    end
    integer word_index;
    initial forever begin
        wait(!reset && sd_rd);
        repeat (2) @(negedge clk);
        sd_ack = 1;
        sectors = sectors + 1;
        for (word_index = 0; word_index < 256; word_index = word_index + 1) begin
            sd_buff_addr = 13'(word_index);
            sd_buff_dout = 16'h5555;
            if (sd_lba == 0) begin
                if (word_index == 0) sd_buff_dout = header ? 16'h0001 : 16'h0000;
                if (word_index == 40) sd_buff_dout = 16'h0003;
                if (word_index == 41) sd_buff_dout = header ? 16'h0001 : 16'h0000;
            end
            sd_buff_wr = 1;
            @(negedge clk);
        end
        sd_buff_wr = 0;
        sd_ack = 0;
        wait(!sd_rd);
    end

    task automatic mount_case(input [63:0] bytes, input bit dc42,
                              input bit rejected, input [23:0] base,
                              input bit change_base, input bit first_word_only);
        integer timeout_ticks, writes_expected;
        reg [63:0] payload;
        begin
            @(negedge clk); reset = 1;
            repeat (3) @(negedge clk);
            reset = 0; img_size = bytes; header = dc42;
            base_addr = base; expected_base = base; sectors = 0;
            repeat (2) @(negedge clk);
            img_mounted = 1;
            @(negedge clk); img_mounted = 0;
            if (change_base) base_addr = 24'he00000;
            timeout_ticks = 0;
            while (!done && !(first_word_only && writes > 0)) begin
                @(negedge clk);
                timeout_ticks = timeout_ticks + 1;
                if (timeout_ticks > 12000) $fatal(1, "mount case timeout size=%h", bytes);
            end
            if (rejected) begin
                if (writes != 0 || size != 0 || is_dc42 || raw_img || dc42_fmt != 0 || loading || sd_rd || wr_req)
                    $fatal(1, "rejected mount changed SDRAM or retained media status");
            end else if (first_word_only) begin
                if (writes == 0 || dut.dc42 != dc42 || sectors != 1)
                    $fatal(1, "supported-size first-block probe failed");
            end else begin
                payload = dc42 ? bytes - 64'd84 : bytes;
                writes_expected = int'((payload + 1) >> 1);
                if (writes != writes_expected || size != payload || is_dc42 != dc42 || raw_img == dc42)
                    $fatal(1, "accepted mount data/count/status mismatch size=%h writes=%0d expected=%0d", bytes, writes, writes_expected);
            end
            cases = cases + 1;
        end
    endtask

    initial begin
        if (TEST_WORDS == 64'h200) begin
            mount_case(511, 0, 0, 24'h600000, 0, 0);
            mount_case(512, 0, 0, 24'h600000, 1, 0);
            mount_case(1023, 0, 0, 24'h700000, 0, 0);
            mount_case(1024, 0, 0, 24'h600000, 0, 0);
            mount_case(512, 0, 0, 24'h7ffe00, 0, 0);
            mount_case(1025, 0, 1, 24'h600000, 0, 0);
            mount_case(1108, 0, 1, 24'h600000, 0, 0);
            mount_case(1109, 0, 1, 24'h600000, 0, 0);
            mount_case(596, 1, 0, 24'h600000, 0, 0);
            mount_case(1107, 1, 0, 24'h600000, 0, 0);
            mount_case(1108, 1, 0, 24'h600000, 0, 0);
            mount_case(1109, 1, 1, 24'h600000, 0, 0);
            mount_case(83, 1, 1, 24'h600000, 0, 0);
            mount_case(84, 1, 1, 24'h600000, 0, 0);
            mount_case(512, 0, 1, 24'he00000, 0, 0);
            mount_case(512, 0, 1, 24'h7fff00, 0, 0);
            mount_case(512, 0, 1, 24'hffff00, 0, 0);
            mount_case(64'h20000000200, 0, 1, 24'h600000, 0, 0);
            mount_case(64'h8000000000000000, 0, 1, 24'h600000, 0, 0);
            mount_case(64'hffffffffffffffff, 0, 1, 24'h600000, 0, 0);
        end else if (TEST_WORDS == 64'h100000) begin
            mount_case(409600, 0, 0, 24'h600000, 0, 1);
            mount_case(819200, 0, 0, 24'h600000, 0, 1);
            mount_case(737280, 0, 0, 24'h600000, 0, 1);
            mount_case(1474560, 0, 0, 24'h600000, 0, 1);
            mount_case(409684, 1, 0, 24'h600000, 0, 1);
            mount_case(819284, 1, 0, 24'h600000, 0, 1);
            mount_case(838484, 1, 0, 24'h600000, 0, 1);
            mount_case(737364, 1, 0, 24'h600000, 0, 1);
            mount_case(1474644, 1, 0, 24'h600000, 0, 1);
            mount_case(2097152, 0, 0, 24'h600000, 0, 1);
            mount_case(2097152, 0, 0, 24'h700000, 0, 1);
            mount_case(2097236, 1, 0, 24'h600000, 0, 1);
            mount_case(2097153, 0, 1, 24'h600000, 0, 0);
            mount_case(2097237, 1, 1, 24'h600000, 0, 0);
            mount_case(64'he80200, 0, 1, 24'h600000, 0, 0);
        end else begin
            mount_case(512, 0, 1, 24'h600000, 0, 0);
        end
        $display("PASS loader-bounds region_words=%h cases=%0d ticks=%0d", TEST_WORDS, cases, ticks);
        $finish;
    end
endmodule
