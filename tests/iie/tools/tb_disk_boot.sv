`timescale 1ns/1ps
// Card CPU boots the original Disk II P5 ROM through card_iwm_frontend and
// card_iwm_backend from a WOZ image served by a 16-bit hps_io block model.
// The synthetic host only starts the CPU and ACKs captures (+$0C).
module tb_disk_boot;
    localparam integer IMAGE_BYTES = 1536 + 35 * 13 * 512;
    reg clk = 0, por_n = 0;
    always #15.3845 clk = !clk;

    // Host register port.
    reg req_valid = 0, req_word = 0, req_write = 1;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error, fault, boundary;
    wire [15:0] rsp_rdata, cpu_address, instruction_address;

    // Card memory.
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    reg mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    reg [15:0] memory [0:131071];

    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [15:0] capture_address;
    wire [22:0] iwm_control;
    wire [11:0] iwm_drive;

    card_irq_candidate #(.IWM_BACKEND(1'b1)) dut (
        .clk(clk), .por_n(por_n), .runtime_mode(1'b1),
        .req_valid(req_valid), .req_ready(req_ready), .req_offset(req_offset),
        .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_valid(mem_valid), .mem_ready(!mem_rsp_valid), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata), .fault(fault), .boundary(boundary),
        .cpu_address(cpu_address), .instruction_address(instruction_address),
        .capture_valid(capture_valid), .capture_status(capture_status),
        .capture_address(capture_address), .capture_data(capture_data),
        .capture_count(), .cpu_completed(), .debug_state(), .debug_trace(),
        .iwm_control(iwm_control), .iwm_drive(iwm_drive)
    );

    // Drive backend and its SD block port.
    wire [31:0] sd_lba;
    wire sd_rd, sd_wr;
    reg sd_ack = 0, sd_buff_wr = 0, img_mounted = 0, cold_reset = 1;
    reg [7:0] sd_buff_addr = 0;
    reg [15:0] sd_buff_dout = 0;
    wire [15:0] sd_buff_din;
    card_iwm_backend drive (
        .clk(clk), .cold_reset(cold_reset), .control(iwm_control), .drive(iwm_drive),
        .write_protect(1'b1), .active(),
        .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_wr(sd_wr), .sd_ack(sd_ack),
        .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout), .sd_buff_din(sd_buff_din),
        .sd_buff_wr(sd_buff_wr), .img_mounted(img_mounted), .img_readonly(1'b1),
        .img_size(64'(IMAGE_BYTES))
    );

    reg [7:0] disk [0:IMAGE_BYTES-1];
    integer blocks_read = 0;
    always begin
        wait (sd_rd || sd_wr);
        if (sd_wr) $fatal(1, "write-back on a read-only boot");
        repeat (40) @(posedge clk);
        sd_ack <= 1;
        for (integer i = 0; i < 256; i = i + 1) begin
            sd_buff_addr <= i;
            sd_buff_dout <= {disk[sd_lba * 512 + 2 * i + 1], disk[sd_lba * 512 + 2 * i]};
            @(posedge clk) sd_buff_wr <= 1;
            @(posedge clk) sd_buff_wr <= 0;
            repeat (10) @(posedge clk);
        end
        blocks_read = blocks_read + 1;
        @(posedge clk) sd_ack <= 0;
        wait (!sd_rd && !sd_wr);
    end

    // +trace=N prints the first N instruction fetches.
    integer trace_left = 0;
    initial if (!$value$plusargs("trace=%d", trace_left)) trace_left = 0;
    always @(posedge clk) if (trace_left > 0 && dut.cpu_ready && dut.cpu_sync) begin
        trace_left <= trace_left - 1;
        $display("fetch %h op=%h monitor=%b A=%h X=%h", cpu_address, dut.cpu_rdata, dut.monitor_active,
                 dut.processor.cpu.reg_a, dut.processor.cpu.reg_x);
    end
    always @(posedge clk) begin
        if (fault || boundary)
            $fatal(1, "card fault cause=%0d pc=%h bus=%h", dut.first_fault, instruction_address, cpu_address);
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (mem_valid && !mem_rsp_valid) begin
            if (mem_write) memory[mem_addr] <= mem_wdata;
            mem_rdata <= memory[mem_addr];
            mem_rsp_valid <= 1;
        end
    end

    task host(input bit word_access, input [5:0] offset, input [15:0] value);
        begin
            @(negedge clk);
            req_word = word_access; req_offset = offset; req_wdata = value; req_valid = 1;
            do @(posedge clk); while (!req_ready);
            @(negedge clk); req_valid = 0;
            wait (rsp_valid);
            if (rsp_error) $fatal(1, "host transaction failed offset=%h", offset);
            @(negedge clk);
        end
    endtask

    // +heads logs every head move with the phase lines.
    bit log_heads;
    initial log_heads = $test$plusargs("heads");
    always @(drive.qtrack) if (log_heads)
        $display("head qtrack=%0d phases=%b pc=%h t=%0d us", drive.qtrack, iwm_control[3:0],
                 instruction_address, $rtoi($realtime / 1e3));

    // Progress, in simulated 100 ms steps.
    integer tenths = 0;
    always begin
        #100000000;
        tenths = tenths + 1;
        $display("t=%0d.%0d s pc=%h qtrack=%0d motor=%b enabled=%b blocks=%0d", tenths / 10, tenths % 10,
                 instruction_address, drive.qtrack, dut.iwm_motor, iwm_drive[11], blocks_read);
        if (tenths >= 40) $fatal(1, "disk boot timeout pc=%h capture=%b/%h/%h", instruction_address,
                                 capture_valid, capture_status, capture_address);
    end

    string image_path, disk_path, out_path;
    integer fd, motor_on_traps = 0;
    bit booted = 0;
    realtime motor_on_time, boot_time;
    initial begin
        if (!$value$plusargs("image=%s", image_path) || !$value$plusargs("disk=%s", disk_path) ||
            !$value$plusargs("out=%s", out_path))
            $fatal(1, "missing +image, +disk or +out");
        $readmemh(image_path, memory);
        $readmemh(disk_path, disk);
        repeat (100) @(negedge clk);
        cold_reset = 0;
        repeat (100) @(negedge clk);
        img_mounted = 1;
        repeat (10) @(negedge clk);
        img_mounted = 0;
        wait (drive.mounted);
        por_n = 1;
        host(0, 33, 16'h20); host(0, 32, 16'h80);
        wait (capture_valid);
        if (capture_status != 8'h80 || capture_address != 16'hFFFC) $fatal(1, "reset capture mismatch");
        host(0, 32, 16'h88); host(0, 12, 0);
        // Service captures until the boot sector's motor-off store.
        while (!booted) begin
            wait (capture_valid);
            // The held access completes on the CPU's next pacer slot after the ACK.
            if (capture_address == 16'hC0E9 && capture_status == 8'h38) begin
                motor_on_traps = motor_on_traps + 1;
                motor_on_time = $realtime;
                $display("motor on  pc=%h t=%0d us", instruction_address, $rtoi($realtime / 1e3));
                host(0, 12, 0);
                repeat (200) @(negedge clk);
                if (!dut.iwm_motor) $fatal(1, "motor-on ACK did not reach the IWM");
            end else if (capture_address == 16'hC0E8 && capture_status == 8'h28) begin
                $display("motor off pc=%h t=%0d us", instruction_address, $rtoi($realtime / 1e3));
                booted = instruction_address == 16'h0803;
                if (booted) boot_time = $realtime;
                host(0, 12, 0);
                repeat (200) @(negedge clk);
                if (dut.iwm_motor) $fatal(1, "motor-off ACK did not reach the IWM");
            end else
                $fatal(1, "unexpected capture status=%h address=%h data=%h pc=%h", capture_status,
                       capture_address, capture_data, instruction_address);
        end
        wait (instruction_address == 16'h0806);
        fd = $fopen(out_path, "w");
        $fwrite(fd, "MOTOR_ON_TRAPS %0d\nMOTOR_ON_MS %0d\nBOOT_MS %0d\nTRACK_ID %0d\nBLOCKS %0d\nSLOT %02x\n",
                motor_on_traps, $rtoi(motor_on_time / 1e6), $rtoi(boot_time / 1e6), drive.track_id,
                blocks_read, memory[17'h15][15:8]);
        for (integer i = 0; i < 128; i = i + 1)
            $fwrite(fd, "%02x\n%02x\n", memory[17'h400 + i][7:0], memory[17'h400 + i][15:8]);
        $fclose(fd);
        $display("DONE");
        $finish;
    end
endmodule
