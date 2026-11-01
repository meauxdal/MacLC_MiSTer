`timescale 1ns/1ps
module tb_download;
    reg clk_sys = 0, clk_mem = 0;
    integer clock_phase = 0;
    initial begin
        if ($value$plusargs("PHASE=%d", clock_phase)) begin end
        #(clock_phase);
        forever #10 clk_sys = !clk_sys;
    end
    always #5 clk_mem = !clk_mem;
    reg por_n = 0, cold_init = 1, early_init = 0, warm_request = 0;
    reg hps_fenced = 0, dio_download = 0, ioctl_write = 0, manual_stop = 0;
    reg [15:0] ioctl_data = 0;
    reg [23:0] dio_addr = 0;
    reg ldr_active = 0, wc_active = 0, ldr_req = 0, wc_req = 0;
    reg [23:0] ldr_addr = 0;
    reg [21:0] wc_addr = 0;
    reg [15:0] ldr_data = 0, wc_data = 0;
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
        .loader_stopped(stop_sys && !ldr_active), .committer_stopped(stop_sys && !wc_active),
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
`ifdef UNSAFE_EARLY_INIT
        .init(cold_init || warm_init || early_init || raw_ack),
`else
        .init(cold_init || warm_init || early_init),
`endif
        .clk_64(clk_mem), .clk_8(mem_phase >= 4),
        .din(16'b0), .dout(), .addr(24'b0), .ds(2'b11), .oe(1'b0), .we(1'b0),
        .flp_win(1'b0), .flp_addr(24'b0), .flp_guard(1'b0),
        .dl_req(dl_req), .dl_slot(dl_slot), .dl_addr(dl_addr), .dl_din(dl_data), .dl_ack(raw_ack),
        .eth_req(1'b0), .eth_we(1'b0), .eth_addr(24'b0), .eth_din(16'b0),
        .eth_ack(), .eth_dout(), .cpu_done(), .cpu_dout()
    );

    reg [15:0] memory [0:767], expected [0:767];
    integer offered [0:767], committed [0:767];
    reg [11:0] rows [0:3];
    reg [22:0] chip_address;
    integer accepts = 0, posts = 0, stores = 0, resets = 0, ticks = 0, posted_before_cas = 0;
    integer slot_drain = 0, held_tail_checks = 0, init_count = 0, early_ticks = 0;
    reg old_ack = 0, old_init = 0, old_req = 0;
    reg [23:0] old_addr = 0;
    reg [15:0] old_data = 0;
    function automatic integer cell_index(input [23:0] address);
        begin
            if (address >= 24'h500000 && address < 24'h500100) cell_index = int'(address[7:0]);
            else if (address >= 24'h600000 && address < 24'h600100) cell_index = 256 + int'(address[7:0]);
            else if (address >= 24'h610000 && address < 24'h610100) cell_index = 512 + int'(address[7:0]);
            else cell_index = -1;
        end
    endfunction
    integer at;
    always @(negedge clk_mem) begin
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0100: begin
                chip_address = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                at = cell_index({1'b0, chip_address});
                if (at < 0 || sd_dqm != 0) $fatal(1, "write outside checked allocation %h", chip_address);
                if (offered[at] != 1 || committed[at] != 0 || sd_data !== expected[at])
                    $fatal(1, "physical CAS mismatch address=%h data=%h expected=%h offered=%0d committed=%0d", chip_address, sd_data, expected[at], offered[at], committed[at]);
                memory[at] = sd_data;
                committed[at] = committed[at] + 1;
                stores = stores + 1;
            end
            default: begin end
        endcase
    end
    always @(posedge clk_mem) begin
        ticks = ticks + 1;
        if (ticks > 60000) $fatal(1, "watchdog state=%0d grant=%0d lock=%b pending=%b req=%b ack=%b posts=%0d stores=%0d", sequencer.state, ingress.dl_grant, ingress.dl_locked, ingress.rom_pending, dl_req, dl_ack, posts, stores);
        if (raw_ack && !old_ack) begin
            posts = posts + 1;
            if (posts > stores) posted_before_cas = posted_before_cas + 1;
`ifdef UNSAFE_EARLY_INIT
            early_init <= 1;
`endif
        end
        old_ack = raw_ack;
`ifdef UNSAFE_EARLY_INIT
        if (early_init) begin
            early_ticks = early_ticks + 1;
            if (early_ticks == 6 && posts != stores)
                $fatal(1, "immediate init discarded posted write before CAS posts=%0d CAS=%0d", posts, stores);
        end
`endif
        if (warm_init && !old_init) begin
            init_count = init_count + 1;
            if (!hps_fenced || dio_download || !local_drained || !stopped || posts != stores || accepts != stores)
                $fatal(1, "reinit before fenced download drain accepts=%0d posts=%0d CAS=%0d", accepts, posts, stores);
        end
        old_init = warm_init;
        if (completed) resets = resets + 1;
        if (stop_sys && dl_req && dl_slot) slot_drain = slot_drain + 1;
    end
    always @(posedge clk_sys) begin
        if (por_n && protocol_fault) $fatal(1, "unexpected ingress protocol fault");
        if (por_n && ingress.dl_locked && ingress.dl_grant != 2 && ingress.dl_rom_sel)
            $fatal(1, "late ROM overrode locked owner");
        if (por_n && old_req && dl_req && (old_addr !== dl_addr || old_data !== dl_data))
            $fatal(1, "registered payload changed during request");
        old_req = dl_req; old_addr = dl_addr; old_data = dl_data;
        if (por_n && stop_sys && !ioctl_wait) $fatal(1, "stop did not backpressure HPS");
    end
    task automatic expect_word(input [23:0] address, input [15:0] value);
        integer index;
        begin
            index = cell_index(address);
            if (index < 0 || offered[index] != 0) $fatal(1, "invalid stimulus address");
            offered[index] = 1; expected[index] = value; accepts = accepts + 1;
        end
    endtask
    task automatic rom_word(input integer offset, input [15:0] value);
        begin
            @(negedge clk_sys);
            if (ingress.rom_pending || (ingress.dl_locked && ingress.dl_grant == 2))
                $fatal(1, "ROM producer overflow in stimulus");
            expect_word(24'h500000 + offset[23:0], {value[7:0], value[15:8]});
            dio_addr = offset[23:0]; ioctl_data = value; ioctl_write = 1;
            @(negedge clk_sys); ioctl_write = 0; dio_addr = 24'h03ffff; ioctl_data = ~value;
            wait(!ingress.rom_pending);
            repeat (3) @(negedge clk_sys);
            if (dl_req && ingress.dl_grant == 2)
                $fatal(1, "backpressure flag became ROM request after accepted word retired");
        end
    endtask
    task automatic owner_word(input integer owner, input integer offset, input [15:0] value);
        begin
            @(negedge clk_sys);
            expect_word((owner == 0 ? 24'h610000 : 24'h600000) + offset[23:0], value);
            if (owner == 0) begin ldr_active = 1; ldr_addr = 24'h610000 + offset[23:0]; ldr_data = value; ldr_req = 1; end
            else begin wc_active = 1; wc_addr = {offset[20:0], 1'b0}; wc_data = value; wc_req = 1; end
            if (owner == 0) wait(ldr_ack); else wait(wc_ack);
            @(negedge clk_sys);
            if (owner == 0) begin ldr_req = 0; ldr_data = ~value; ldr_addr = 24'h710000; end
            else begin wc_req = 0; wc_data = ~value; wc_addr = 22'h3ffffe; end
            if (owner == 0) wait(!ldr_ack); else wait(!wc_ack);
            @(negedge clk_sys);
            if (owner == 0) ldr_active = 0; else wc_active = 0;
        end
    endtask
    task automatic pulse_warm;
        begin
            @(negedge clk_sys); warm_request = 1;
            repeat (3) @(negedge clk_sys);
            warm_request = 0;
        end
    endtask
    task automatic wait_reset(input integer before_reset);
        begin
            wait(resets == before_reset + 1);
            wait(!stop_sys && !busy);
            repeat (4) @(negedge clk_sys);
            hps_fenced = 0;
        end
    endtask
    task automatic verify_memory;
        integer index;
        begin
            for (index = 0; index < 768; index = index + 1)
                if (memory[index] !== expected[index] || offered[index] != committed[index])
                    $fatal(1, "finite memory comparison failed cell=%0d", index);
            if (accepts != stores || posts != stores) $fatal(1, "word accounting accepts=%0d posts=%0d CAS=%0d", accepts, posts, stores);
        end
    endtask

    integer i, owner, before_reset, before_init, first_posts;
    initial begin
        for (i = 0; i < 768; i = i + 1) begin
            memory[i] = 16'h5aa5; expected[i] = 16'h5aa5; offered[i] = 0; committed[i] = 0;
        end
        repeat (5) @(negedge clk_mem); cold_init = 0;
        wait(memory_ready);
        @(negedge clk_sys); por_n = 1;
        wait(!stop_sys);
        // Stub producers represent accepted operations, not full loader/committer FSMs.
        fork owner_word(0, 0, 16'h1234); owner_word(1, 0, 16'h5678); join
        wait(local_drained); verify_memory();

        // A late ROM frame cannot replace either locked non-ROM owner.
        for (owner = 0; owner < 2; owner = owner + 1) begin
            hold_enable = 1;
            fork
                owner_word(owner, 1, 16'h3210 + owner[15:0]);
                begin
                    wait(ingress.dl_locked && ingress.dl_grant == owner[1:0]);
                    @(negedge clk_sys); manual_stop = 1; dio_download = 1;
                    rom_word(1 + owner, 16'h8001 + owner[15:0]);
                end
                begin
                    wait(raw_ack); wait(!raw_ack);
                    repeat (9) begin
                        @(negedge clk_sys);
                        if (!ingress.dl_locked || ingress.dl_grant != owner[1:0] || local_drained)
                            $fatal(1, "held ACK tail released ownership");
                        held_tail_checks = held_tail_checks + 1;
                    end
                    hold_enable = 0;
                end
            join
            @(negedge clk_sys); dio_download = 0;
            wait(local_drained); verify_memory(); manual_stop = 0;
        end

        // Active session defers entry; a low active flag without a fence cannot authorize init.
        dio_download = 1; before_reset = resets; before_init = init_count;
        pulse_warm();
        repeat (25) @(negedge clk_sys);
        if (stop_sys || init_count != before_init) $fatal(1, "active ROM session did not defer reset");
        rom_word(10, 16'h1112);
        @(negedge clk_sys); dio_download = 0;
        wait(stop_sys);
        repeat (25) @(negedge clk_sys);
        if (init_count != before_init || !local_drained || stopped) $fatal(1, "missing admission fence permitted reset");
        hps_fenced = 1; wait_reset(before_reset); verify_memory();

        // Offered word coincides with stop becoming visible, then session stays open.
        before_reset = resets; before_init = init_count;
        fork
            pulse_warm();
            begin
                wait(sequencer.stop_sync1 && !stop_sys);
                @(negedge clk_sys);
                dio_download = 1; ioctl_write = 1; dio_addr = 11; ioctl_data = 16'h2233;
                expect_word(24'h50000b, 16'h3322);
                @(negedge clk_sys); ioctl_write = 0; ioctl_data = 16'hdead; dio_addr = 24'h03ffff;
                wait(!ingress.rom_pending);
                repeat (15) @(negedge clk_sys);
                if (init_count != before_init || !stop_sys) $fatal(1, "late active session failed reset deferral");
                dio_download = 0;
                repeat (15) @(negedge clk_sys);
                if (init_count != before_init || stopped) $fatal(1, "late session end replaced admission fence");
                hps_fenced = 1;
            end
        join
        wait_reset(before_reset); verify_memory();

        // Accepted operation drains both words despite stop. The next offer follows
        // the first REQ-low clock immediately, while raw ACK is extended.
        for (owner = 0; owner < 2; owner = owner + 1) begin
            before_reset = resets;
            hold_enable = 1;
            first_posts = posts;
            @(negedge clk_sys);
            expect_word((owner == 0 ? 24'h610000 : 24'h600000) + 24'd20, 16'h4400 + owner[15:0]);
            if (owner == 0) begin ldr_active = 1; ldr_addr = 24'h610014; ldr_data = 16'h4400; ldr_req = 1; end
            else begin wc_active = 1; wc_addr = 40; wc_data = 16'h4401; wc_req = 1; end
            fork
                pulse_warm();
                begin
                    if (owner == 0) wait(ldr_ack); else wait(wc_ack);
                    @(negedge clk_sys);
                    if (owner == 0) ldr_req = 0; else wc_req = 0;
                    @(negedge clk_sys);
                    expect_word((owner == 0 ? 24'h610000 : 24'h600000) + 24'd21, 16'h5500 + owner[15:0]);
                    if (owner == 0) begin ldr_addr = 24'h610015; ldr_data = 16'h5500; ldr_req = 1; end
                    else begin wc_addr = 42; wc_data = 16'h5501; wc_req = 1; end
                    repeat (7) begin
                        @(negedge clk_sys);
                        if ((owner == 0 ? ldr_ack : wc_ack) || warm_init || !ingress.dl_locked)
                            $fatal(1, "next accepted word consumed stale ACK");
                    end
                    hold_enable = 0;
                    if (owner == 0) wait(ldr_ack); else wait(wc_ack);
                    @(negedge clk_sys);
                    if (owner == 0) begin ldr_req = 0; ldr_active = 0; end
                    else begin wc_req = 0; wc_active = 0; end
                    hps_fenced = 1;
                end
            join
            wait_reset(before_reset); verify_memory();
            if (posts != first_posts + 2) $fatal(1, "back-to-back operation accounting");
        end
        if (resets != 4 || init_count != 4 || posted_before_cas != accepts || slot_drain == 0 || held_tail_checks != 18)
            $fatal(1, "coverage incomplete resets=%0d init=%0d earlypost=%0d accepts=%0d slots=%0d tails=%0d", resets, init_count, posted_before_cas, accepts, slot_drain, held_tail_checks);
        $display("PASS download phase=%0d accepted=%0d posted=%0d CAS=%0d resets=%0d cells=768 held_tail=%0d drain_slots=%0d", clock_phase, accepts, posts, stores, resets, held_tail_checks, slot_drain);
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
