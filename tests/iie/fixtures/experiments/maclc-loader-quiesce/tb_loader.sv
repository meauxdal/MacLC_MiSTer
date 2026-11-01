`timescale 1ns/1ps
module tb_loader;
    reg clk_sys = 0, clk_mem = 0;
    integer clock_phase = 0;
    initial begin
        if ($value$plusargs("PHASE=%d", clock_phase)) begin end
        #(clock_phase);
        forever #10 clk_sys = !clk_sys;
    end
    always #5 clk_mem = !clk_mem;
    reg por_n = 0, cold_init = 1, warm_request = 0;
    reg hps_fenced = 0, dio_download = 0, ioctl_write = 0, manual_stop = 0;
    reg [15:0] ioctl_data = 0;
    reg [23:0] dio_addr = 0;
    wire ldr_req;
    reg wc_req = 0;
    wire [23:0] ldr_addr;
    reg [21:0] wc_addr = 0;
    wire [15:0] ldr_data;
    reg [15:0] wc_data = 0;
    wire ldr_ack, wc_ack, ioctl_wait, local_drained, stopped, protocol_fault;
    wire stop_sys, stop_mem, freeze, warm_init, epoch_sys, epoch_mem, busy, completed;
    wire memory_ready, controller_idle;
    reg [3:0] bus_phase = 0;
    always @(posedge clk_sys) bus_phase <= bus_phase + 1'b1;
    wire dio_slot = bus_phase[1:0] == 2'b10;
    wire dl_req, dl_slot;
    wire [23:0] dl_addr;
    wire [15:0] dl_data;
    wire raw_ack;
    reg hold_enable = 0, held_ack = 0;
    always @(posedge clk_mem) begin
        if (!hold_enable) held_ack <= 0;
        else if (raw_ack) held_ack <= 1;
    end
    wire dl_ack = raw_ack || held_ack;
    maclc_download ingress (
        .clk_sys(clk_sys), .pll_locked_s(por_n), .stop(stop_sys || manual_stop), .hps_fenced(hps_fenced),
        .loader_stopped(loader_stopped), .committer_stopped(stop_sys),
        .ioctl_write(ioctl_write), .ioctl_data(ioctl_data), .dio_addr(dio_addr), .dio_download(dio_download),
        .flp_int_wr_req(ldr_req), .flp_int_wr_addr(ldr_addr), .flp_int_wr_data(ldr_data),
        .wc_req(wc_req), .wc_addr(wc_addr), .wc_data(wc_data), .dioBusControl(dio_slot),
        .sdram_dl_ack(dl_ack), .ioctl_wait(ioctl_wait), .local_drained(local_drained),
        .stopped(stopped), .protocol_fault(protocol_fault), .flp_int_wr_ack(ldr_ack), .wc_ack(wc_ack),
        .sdram_dlreq_q(dl_req), .sdram_dlslot_q(dl_slot), .sdram_dladdr_q(dl_addr), .sdram_dldin_q(dl_data)
    );
    card_warm_reset sequencer (
        .clk_sys(clk_sys), .clk_mem(clk_mem), .por_n_sys(por_n), .por_n_mem(por_n),
        .warm_request_sys(warm_request), .download_active_sys(dio_download),
        .producers_stopped_sys(stopped), .drained_sys(local_drained), .native_drained_mem(1'b1),
        .controller_ready_mem(memory_ready), .controller_idle_mem(controller_idle),
        .stop_sys(stop_sys), .stop_mem(stop_mem), .controller_quiesce(freeze), .controller_init(warm_init),
        .epoch_reset_sys(epoch_sys), .epoch_reset_mem(epoch_mem), .busy(busy), .completed(completed)
    );
    reg [2:0] mem_phase = 0;
    always @(posedge clk_mem) mem_phase <= mem_phase + 1'b1;
    wire sd_clk, sd_cs, sd_ras, sd_cas, sd_we;
    wire [15:0] sd_data;
    wire [12:0] sd_addr;
    wire [1:0] sd_ba, sd_dqm;
    sdram #(.ENABLE_QUIESCE(1)) controller (
        .warm_quiesce(freeze), .warm_idle(controller_idle), .memory_ready(memory_ready),
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(16'b0), .sd_addr(sd_addr),
        .sd_dqm(sd_dqm), .sd_ba(sd_ba), .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(cold_init || warm_init),
        .clk_64(clk_mem), .clk_8(mem_phase >= 4),
        .din(16'b0), .dout(), .addr(24'b0), .ds(2'b11), .oe(1'b0), .we(1'b0),
        .flp_win(1'b0), .flp_addr(24'b0), .flp_guard(1'b0),
        .dl_req(dl_req), .dl_slot(dl_slot), .dl_addr(dl_addr), .dl_din(dl_data), .dl_ack(raw_ack),
        .eth_req(1'b0), .eth_we(1'b0), .eth_addr(24'b0), .eth_din(16'b0),
        .eth_ack(), .eth_dout(), .cpu_done(), .cpu_dout()
    );

    reg img_mounted = 0, img_readonly = 0;
    reg [63:0] img_size = 0;
    reg [23:0] base_addr = 0;
    wire [31:0] sd_lba;
    wire sd_rd, loading, done, loader_stopped, pending, overflow, admitted;
    wire [63:0] size;
    wire readonly, raw_img, is_dc42, media_ds;
    wire [7:0] dc42_fmt;
    wire [15:0] hdr_data;
    reg [5:0] hdr_addr = 0;
    reg sd_ack = 0, sd_buff_wr = 0;
    reg [12:0] sd_buff_addr = 0;
    reg [15:0] sd_buff_dout = 0;
    loader_admission loader (
        .clk_sys(clk_sys), .reset(!por_n), .stop(stop_sys || manual_stop),
        .img_mounted(img_mounted), .img_size(img_size), .img_readonly(img_readonly), .base_addr(base_addr),
        .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_ack(sd_ack),
        .sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout), .sd_buff_wr(sd_buff_wr),
        .wr_addr(ldr_addr), .wr_data(ldr_data), .wr_req(ldr_req), .wr_ack(ldr_ack),
        .loading(loading), .done(done), .stopped(loader_stopped), .size(size),
        .readonly(readonly), .raw_img(raw_img), .is_dc42(is_dc42), .media_ds(media_ds),
        .dc42_fmt(dc42_fmt), .hdr_addr(hdr_addr), .hdr_data(hdr_data),
        .pending(pending), .overflow(overflow), .admitted(admitted)
    );
    localparam CELLS = 10240;
    reg [15:0] memory [0:CELLS-1], expected [0:CELLS-1];
    integer committed [0:CELLS-1];
    reg [11:0] rows [0:3];
    reg [22:0] chip_address;
    integer posts = 0, stores = 0, resets = 0, ticks = 0, init_count = 0;
    integer planned = 0, done_count = 0, admissions = 0, blocks = 0, tail_checks = 0;
    integer round_id = 0, file_blocks = 2, at, j, k, first_done, first_init;
    reg dc_image = 0, old_ack = 0, old_init = 0;
    reg [63:0] active_size = 0;
    function automatic [15:0] file_word(input integer image, input integer offset, input bit dc);
        begin
            file_word = 16'h8000 ^ (16'(image) << 10) ^ 16'(offset);
            if (offset == 0) file_word = dc ? 16'h0004 : 16'h0080;
            if (offset == 40) file_word = dc ? 16'h0002 : 16'h1234;
            if (offset == 41) file_word = dc ? 16'h0001 : 16'h5678;
            if (image == 7) begin
                case (offset)
                    554: file_word = 16'h4442;
                    563: file_word = 16'h0a00;
                    564: file_word = 16'h0000;
                    565: file_word = 16'h0002;
                    default: begin end
                endcase
            end
        end
    endfunction
    function automatic [15:0] swapped(input [15:0] value);
        swapped = {value[7:0], value[15:8]};
    endfunction
    function automatic integer cell_index(input [23:0] address);
        cell_index = (address >= 24'h610000 && address < 24'h612800) ? int'(address) - 32'h610000 : -1;
    endfunction
    // Finite pin-level command/data accounting, including untouched sentinels.
    always @(negedge clk_mem) begin
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0100: begin
                chip_address = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                at = cell_index({1'b0, chip_address});
                if (at < 0 || sd_dqm != 0) $fatal(1, "write outside retained allocation");
                if (expected[at] === 16'h5aa5 || committed[at] != 0 || sd_data !== expected[at])
                    $fatal(1, "physical word mismatch cell=%0d got=%h expected=%h count=%0d", at, sd_data, expected[at], committed[at]);
                memory[at] = sd_data;
                committed[at] = committed[at] + 1;
                stores = stores + 1;
            end
            default: begin end
        endcase
    end
    always @(posedge clk_mem) begin
        ticks = ticks + 1;
        if (ticks > 2000000) $fatal(1, "watchdog loader=%0d reset=%0d stores=%0d planned=%0d", loader.engine.state, sequencer.state, stores, planned);
        if (raw_ack && !old_ack) posts = posts + 1;
        old_ack = raw_ack;
        if (warm_init && !old_init) begin
            init_count = init_count + 1;
            if (!stopped || !local_drained || !loader_stopped || planned != stores || posts != stores)
                $fatal(1, "reinit before whole loader drain");
        end
        old_init = warm_init;
        if (completed) resets = resets + 1;
    end
    always @(posedge clk_sys) begin
        if (por_n && protocol_fault) $fatal(1, "ingress protocol fault");
        if (admitted) begin
            admissions = admissions + 1;
            if (stop_sys || manual_stop) $fatal(1, "deferred mount admitted during stop");
        end
        if (loading && loader.engine.img_size_l !== active_size)
            $fatal(1, "active mount metadata overwritten");
        if (done) begin
            done_count = done_count + 1;
            if (size !== active_size - (dc_image ? 64'd84 : 64'd0) || readonly !== 1'b1 ||
                is_dc42 !== dc_image || raw_img === dc_image || media_ds !== (round_id != 7))
                $fatal(1, "completed image metadata mismatch");
        end
        if (stop_sys && admitted) $fatal(1, "deferred mount admitted during stop");
    end
    // The service retains this image's backing bytes until its load completes.
    initial forever begin
        @(negedge clk_sys);
        if (sd_rd && !sd_ack) begin
            repeat (4) @(negedge clk_sys);
            sd_ack = 1;
            repeat (3) @(negedge clk_sys);
            for (k = 0; k < 256; k = k + 1) begin
                sd_buff_addr = 13'(k);
                sd_buff_dout = file_word(round_id, int'(sd_lba) * 256 + k, dc_image);
                sd_buff_wr = 1;
                @(negedge clk_sys);
            end
            sd_buff_wr = 0;
            repeat (4) @(negedge clk_sys);
            sd_ack = 0;
            blocks = blocks + 1;
        end
    end
    task automatic mount(input [63:0] bytes, input [23:0] base);
        begin
            @(negedge clk_sys);
            img_size = bytes; img_readonly = 1; base_addr = base; img_mounted = 1;
            @(negedge clk_sys);
            img_mounted = 0; img_size = 64'hdeadbeef; img_readonly = 0; base_addr = 24'h710000;
        end
    endtask
    task automatic pulse_warm;
        begin
            @(negedge clk_sys); warm_request = 1;
            repeat (3) @(negedge clk_sys); warm_request = 0;
        end
    endtask
    task automatic verify_memory;
        integer index;
        begin
            for (index = 0; index < CELLS; index = index + 1)
                if (memory[index] !== expected[index] || committed[index] != (expected[index] == 16'h5aa5 ? 0 : 1))
                    $fatal(1, "full memory comparison cell=%0d", index);
            if (stores != planned || posts != planned) $fatal(1, "word accounting");
        end
    endtask
    integer i, offset, words, reset_before, before_admissions;
    initial begin
        for (i = 0; i < CELLS; i = i + 1) begin
            memory[i] = 16'h5aa5; expected[i] = 16'h5aa5; committed[i] = 0;
        end
        repeat (5) @(negedge clk_mem); cold_init = 0;
        wait(memory_ready);
        @(negedge clk_sys); por_n = 1;
        wait(!stop_sys);
        for (j = 0; j < 8; j = j + 1) begin
            round_id = j; dc_image = j[0]; file_blocks = j == 7 ? 3 : 2;
            active_size = dc_image ? 64'(file_blocks * 512 - 20) : 64'(file_blocks * 512);
            offset = dc_image ? 42 : 0;
            words = file_blocks * 256 - offset;
            for (i = 0; i < words; i = i + 1)
                expected[j * 1024 + i] = swapped(file_word(j, i + offset, dc_image));
            planned = planned + words;
            first_done = done_count; first_init = init_count; reset_before = resets;
            if (j == 4) begin
                fork
                    begin
                        wait(sd_lba == 1 && loader.engine.drain_idx == 254);
                        hold_enable = 1;
                        wait(raw_ack); wait(!raw_ack);
                        repeat (16) begin
                            @(negedge clk_sys);
                            if (!ingress.dl_locked || local_drained || warm_init)
                                $fatal(1, "held loader ACK tail released drain");
                            tail_checks = tail_checks + 1;
                        end
                        hold_enable = 0;
                    end
                join_none
            end
            mount(active_size, 24'h610000 + 24'(j * 1024));
            wait(loading);
            case (j)
                0: wait(sd_rd && !sd_ack);
                1: wait(sd_ack && sd_buff_wr);
                2: wait(loader.engine.state == 2);
                3: wait(ldr_req && !ldr_ack);
                4: wait(sd_lba == 1 && loader.engine.drain_idx == 255 && ldr_ack);
                5: wait(loader.engine.state == 4);
                6: wait(loader.engine.state == 5);
                7: wait(sd_lba == 2 && sd_ack);
            endcase
            // Retain an unmount as stop becomes visible.
            fork
                pulse_warm();
                begin
                    wait(sequencer.stop_sync1 && !stop_sys);
                    mount(0, 24'h620000);
                    wait(stop_sys);
                    wait(pending);
                end
            join
            hps_fenced = 1;
            wait(resets == reset_before + 1);
            if (!pending || done_count != first_done + 1 || init_count != first_init + 1)
                $fatal(1, "deferred mount lost or active load incomplete");
            wait(!stop_sys && !busy);
            wait(!pending);
            repeat (6) @(negedge clk_sys);
            if (size != 0 || loading || readonly != 1) $fatal(1, "deferred unmount metadata lost");
            if (dc_image) begin
                for (i = 0; i < 42; i = i + 1) begin
                    @(negedge clk_sys); hdr_addr = 6'(i);
                    repeat (2) @(negedge clk_sys);
                    if (hdr_data !== swapped(file_word(j, i, 1)))
                        $fatal(1, "retained DC42 header mismatch");
                end
            end
            verify_memory();
            hps_fenced = 0;
        end
        // Retain a nonzero mount across an idle stop and replay it exactly once.
        @(negedge clk_sys); manual_stop = 1;
        round_id = 8; dc_image = 0; active_size = 512;
        before_admissions = admissions;
        mount(active_size, 24'h612000);
        repeat (12) @(negedge clk_sys);
        if (!pending || loading || admissions != before_admissions || !loader_stopped)
            $fatal(1, "idle stop failed to retain mount");
        reset_before = resets;
        hps_fenced = 1;
        pulse_warm();
        wait(resets == reset_before + 1);
        if (!pending || loading) $fatal(1, "nonzero mount did not survive warm reinit");
        wait(!stop_sys && !busy);
        for (i = 0; i < 256; i = i + 1) expected[8192 + i] = swapped(file_word(8, i, 0));
        planned = planned + 256;
        @(negedge clk_sys); manual_stop = 0;
        wait(done); wait(!done); wait(local_drained);
        repeat (12) @(negedge clk_mem);
        verify_memory();
        if (admissions != before_admissions + 1) $fatal(1, "mount replay duplicated");
        // A second retained event cannot silently replace the first.
        @(negedge clk_sys); manual_stop = 1;
        mount(512, 24'h612400);
        mount(0, 24'h710000);
        repeat (8) @(negedge clk_sys);
        if (!overflow || loader_stopped || !pending || loader.pending_size != 512 || loader.pending_base != 24'h612400)
            $fatal(1, "mount overflow did not fail closed");
        if (resets != 9 || blocks != 18 || done_count != 9 || tail_checks != 16)
            $fatal(1, "coverage incomplete resets=%0d blocks=%0d done=%0d", resets, blocks, done_count);
        $display("PASS loader phase=%0d words=%0d posted=%0d CAS=%0d resets=%0d blocks=%0d images=%0d cells=%0d tails=%0d overflow=1", clock_phase, planned, posts, stores, resets, blocks, done_count, CELLS, tail_checks);
        $finish;
    end
endmodule

module altddio_out #(
    parameter extend_oe_disable = "OFF", intended_device_family = "Cyclone V",
              invert_output = "OFF", lpm_hint = "UNUSED", lpm_type = "altddio_out",
              oe_reg = "UNREGISTERED", power_up_high = "OFF", width = 1
) (
    input wire [width-1:0] datain_h, datain_l,
    input wire outclock, aclr, aset, oe, outclocken, sclr, sset,
    output wire [width-1:0] dataout
);
    assign dataout = outclock ? datain_h : datain_l;
endmodule
