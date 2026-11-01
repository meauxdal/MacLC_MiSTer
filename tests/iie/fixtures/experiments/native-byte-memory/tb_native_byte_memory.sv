`timescale 1ns/1ps
module tb_native_byte_memory;
    parameter ENABLE_MASK = 1, WRONG_BE = 0, FULL_WORD_ONLY = 0;
    parameter NATIVE_FAIR_MODE = 0;
    parameter [23:0] BASE_WORD = 24'h540000;
    reg clk = 0;
    always #5 clk = !clk;
    reg [2:0] phase = 0;
    always @(posedge clk) phase <= phase + 3'd1;
    wire clk8 = phase >= 4;
    reg por_n = 0, reset_request = 0;
    wire arb_drained, adapter_drained;
    reg [1:0] req_valid = 0, req_write = 0, rsp_ready = 0;
    wire [1:0] req_ready, rsp_valid;
    reg [17:0] host_addr = 0, card_addr = 0;
    reg [15:0] host_wdata = 0, card_wdata = 0;
    reg [1:0] host_be = 3, card_be = 3;
    wire [15:0] rsp_rdata;
    wire rsp_denied, mem_valid, mem_ready, mem_write, mem_rsp_valid, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata, mem_rdata;
    wire [1:0] mem_be, native_ds;
    wire native_req, native_we, native_ack;
    wire [23:0] native_addr;
    wire [15:0] native_din, native_dout;
    wire adapter_req, adapter_we, adapter_ack;
    wire [23:0] adapter_addr;
    wire [15:0] adapter_din, adapter_dout, writeback_data;
    wire [1:0] adapter_ds, client_ack;
    reg writeback_req = 0;
    integer writeback_services = 0;
    assign adapter_ack = client_ack[0];
    card_byte_native_port_mux ownership (
        .clk(clk), .por_n(por_n), .reset_request(reset_request && arb_drained && adapter_drained),
        .drained(), .client_req({writeback_req, adapter_req}), .client_we({1'b0, adapter_we}),
        .card_addr(adapter_addr), .floppy_addr(24'h600000),
        .card_din(adapter_din), .floppy_din(16'b0), .card_ds(adapter_ds), .floppy_ds(2'b11),
        .client_ack(client_ack), .card_dout(adapter_dout), .floppy_dout(writeback_data),
        .native_req(native_req), .native_we(native_we), .native_addr(native_addr),
        .native_din(native_din), .native_ds(native_ds), .native_ack(native_ack), .native_dout(native_dout)
    );

    card_byte_memory_arbiter arb (
        .clk(clk), .por_n(por_n), .reset_request(reset_request), .drained(arb_drained),
        .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
        .req_write_allowed(2'b11), .host_addr(host_addr), .card_addr(card_addr),
        .host_wdata(host_wdata), .card_wdata(card_wdata), .host_be(host_be), .card_be(card_be),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_denied(rsp_denied),
        .mem_valid(mem_valid), .mem_ready(mem_ready), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_be(mem_be), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata)
    );
    card_byte_native_adapter #(.BASE_WORD(BASE_WORD)) adapter (
        .clk(clk), .por_n(por_n), .reset_request(reset_request && arb_drained), .drained(adapter_drained),
        .mem_valid(mem_valid), .mem_ready(mem_ready), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_be(mem_be), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata), .native_req(adapter_req),
        .native_we(adapter_we), .native_addr(adapter_addr), .native_din(adapter_din),
        .native_ack(adapter_ack), .native_dout(adapter_dout), .native_ds(adapter_ds)
    );

    reg init = 1;
    reg host_oe = 0, flp_win = 0, flp_guard = 0;
    wire cpu_done;
    wire [15:0] cpu_dout, floppy_dout;
    wire sd_clk, sd_cs, sd_ras, sd_cas, sd_we;
    wire [15:0] sd_data;
    reg [15:0] chip_dout = 0;
    wire [12:0] sd_addr;
    wire [1:0] sd_ba, sd_dqm;
    sdram #(.NATIVE_BYTE_ENABLE(ENABLE_MASK)
`ifdef HAS_FAIR_NATIVE
        , .FAIR_NATIVE_ADMISSION(NATIVE_FAIR_MODE)
`endif
    ) controller (
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_dout),
        .sd_addr(sd_addr), .sd_dqm(sd_dqm), .sd_ba(sd_ba),
        .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(init), .clk_64(clk), .clk_8(clk8), .din(16'b0), .dout(floppy_dout),
        .addr(24'h000100), .ds(2'b11), .oe(host_oe), .we(1'b0),
        .flp_win(flp_win), .flp_addr(24'h600000), .flp_guard(flp_guard),
        .dl_req(1'b0), .dl_slot(1'b0), .dl_addr(24'b0), .dl_din(16'b0), .dl_ack(),
        .eth_req(native_req), .eth_we(native_we), .eth_addr(native_addr),
        .eth_ds(FULL_WORD_ONLY ? 2'bxx : (WRONG_BE ? {native_ds[0], native_ds[1]} : native_ds)),
        .eth_din(native_din), .eth_ack(native_ack), .eth_dout(native_dout),
        .cpu_done(cpu_done), .cpu_dout(cpu_dout)
    );

    // Command-level chip model: BL=1, CL=2. This is not an electrical model.
    reg [15:0] store [0:131071];
    reg [15:0] reference_store [0:131071];
    reg [11:0] rows [0:3];
    reg [22:0] read_addr;
    integer read_delay = 0;
    integer chip_reads = 0, chip_writes = 0, refreshes = 0;
    integer low_writes = 0, high_writes = 0, word_writes = 0;
    integer card_commits = 0;
    reg [22:0] command_addr;
    integer chip_index;
    function [15:0] chip_read(input [22:0] address);
        begin
            if (address >= 23'h540000 && address < 23'h560000)
                chip_read = store[address[16:0]];
            else if (address == 23'h000100) chip_read = 16'hbeef;
            else if (address == 23'h600000) chip_read = 16'hcafe;
            else begin
                $fatal(1, "chip read outside test allocation: %h", address);
                chip_read = 0;
            end
        end
    endfunction
    always @(negedge clk) begin
        if (read_delay > 0) begin
            read_delay = read_delay - 1;
            if (read_delay == 0) chip_dout <= chip_read(read_addr);
        end
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0101: begin
                read_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                read_delay = 2;
                chip_reads = chip_reads + 1;
            end
            4'b0100: begin
                command_addr = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                if (command_addr < 23'h540000 || command_addr >= 23'h560000)
                    $fatal(1, "write outside test allocation: %h", command_addr);
                chip_index = {15'b0, command_addr[16:0]};
                if (!sd_dqm[0]) store[chip_index][7:0] = sd_data[7:0];
                if (!sd_dqm[1]) store[chip_index][15:8] = sd_data[15:8];
                chip_writes = chip_writes + 1;
                case (sd_dqm)
                    2'b10: low_writes = low_writes + 1;
                    2'b01: high_writes = high_writes + 1;
                    2'b00: word_writes = word_writes + 1;
                    default: $fatal(1, "empty byte mask reached physical write");
                endcase
                if (controller.src_eth) card_commits = card_commits + 1;
            end
            4'b0001: refreshes = refreshes + 1;
            default: begin end
        endcase
    end

    integer ticks = 0, accepted = 0, completed = 0, backend_accepted = 0;
    integer backend_completed = 0, posted_acks = 0, early_acks = 0;
    integer launch_tick = 0, max_latency = 0, max_normal_latency = 0;
    integer starvation_ticks = 0;
    integer contended_host = 0, contended_card = 0;
    reg frontend_contention = 0;
    reg previous_ack = 0, starve = 0;
    reg bundle_held = 0;
    reg [42:0] frozen_bundle;
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 20000) $fatal(1, "watchdog");
        if (por_n) begin
            if (|(req_valid & req_ready)) begin
                accepted = accepted + 1;
                launch_tick = ticks;
                if (frontend_contention) begin
                    if (req_ready[0] && req_valid[0]) contended_host = contended_host + 1;
                    else contended_card = contended_card + 1;
                end
            end
            if (|(rsp_valid & rsp_ready)) begin
                completed = completed + 1;
                if (ticks - launch_tick > max_latency) max_latency = ticks - launch_tick;
                if (!starve && ticks - launch_tick > max_normal_latency)
                    max_normal_latency = ticks - launch_tick;
            end
            if (mem_valid && mem_ready) backend_accepted = backend_accepted + 1;
            if (mem_rsp_valid && mem_rsp_ready) begin
                backend_completed = backend_completed + 1;
                if (adapter_req || adapter_ack) $fatal(1, "response before handshake rearm");
                if (adapter_we && card_commits != posted_acks)
                    $fatal(1, "write response before chip commit");
            end
            if (native_req) begin
                if (bundle_held && frozen_bundle !== {native_we, native_addr, native_din, native_ds})
                    $fatal(1, "native bundle changed while request held");
                frozen_bundle = {native_we, native_addr, native_din, native_ds};
                bundle_held = 1;
            end else bundle_held = 0;
            if (native_ack && !previous_ack && native_we) begin
                posted_acks = posted_acks + 1;
                if (card_commits < posted_acks) early_acks = early_acks + 1;
                else $fatal(1, "posted-ack negative control did not precede commit");
            end
            previous_ack = native_ack;
        end
    end

    task automatic transaction(input bit owner, input bit write_op, input [17:0] address,
                     input [15:0] value, input [1:0] enables,
                     input [15:0] expected, input bit quiesce);
        reg [15:0] held_data;
        begin
            @(negedge clk);
            if (owner) begin card_addr = address; card_wdata = value; card_be = enables; end
            else begin host_addr = address; host_wdata = value; host_be = enables; end
            req_write[owner] = write_op;
            req_valid[owner] = 1;
            do @(posedge clk); while (!req_ready[owner]);
            if (write_op) begin
                if (enables[0]) reference_store[address[17:1]][7:0] = value[7:0];
                if (enables[1]) reference_store[address[17:1]][15:8] = value[15:8];
            end
            @(negedge clk); req_valid[owner] = 0;
            if (quiesce) begin
                wait(adapter_ack);
                @(negedge clk); reset_request = 1;
                if (adapter_drained || arb_drained) $fatal(1, "early quiescence");
            end
            wait(rsp_valid[owner]);
            @(negedge clk);
            if (rsp_denied || rsp_rdata !== expected) $fatal(1, "response %h expected %h", rsp_rdata, expected);
            held_data = rsp_rdata;
            repeat (7) begin
                @(negedge clk);
                if (!rsp_valid[owner] || rsp_rdata !== held_data)
                    $fatal(1, "response unstable under backpressure");
                if (quiesce && (arb_drained || req_ready != 0)) $fatal(1, "quiesce bypass");
            end
            rsp_ready[owner] = 1;
            @(negedge clk); rsp_ready[owner] = 0;
            if (quiesce) begin
                if (!adapter_drained || !arb_drained) $fatal(1, "drain incomplete");
                reset_request = 0;
            end
        end
    endtask

    reg run_competitors = 0;
    integer host_services = 0, floppy_services = 0;
    initial begin
        wait(run_competitors);
        repeat (6) begin
            @(negedge clk); host_oe = 1;
            wait(cpu_done);
            repeat (5) @(posedge clk);
            @(negedge clk);
            if (cpu_dout !== 16'hbeef) $fatal(1, "host data corrupted");
            host_services = host_services + 1;
            host_oe = 0;
            repeat (18) @(negedge clk);
        end
    end
    initial begin
        wait(run_competitors);
        repeat (6) begin
            @(negedge clk); writeback_req = 1;
            wait(client_ack[1]);
            @(negedge clk);
            if (writeback_data !== 16'hcafe || client_ack[0])
                $fatal(1, "native writeback response/ownership corrupted");
            writeback_services = writeback_services + 1;
            repeat (2) @(negedge clk);
            writeback_req = 0;
            wait(!client_ack[1]);
            repeat (37) @(negedge clk);
        end
    end
    initial begin
        wait(run_competitors);
        repeat (6) begin
            @(negedge clk); flp_guard = 1;
            repeat (4) @(negedge clk);
            flp_win = 1;
            wait(controller.flp_served);
            wait(!controller.seq_busy);
            @(negedge clk);
            if (floppy_dout !== 16'hcafe) $fatal(1, "floppy data corrupted");
            floppy_services = floppy_services + 1;
            flp_win = 0; flp_guard = 0;
            repeat (25) @(negedge clk);
        end
    end

    integer index, ack_snapshot, host_iteration, card_iteration;
    initial begin
        for (index = 0; index < 131072; index = index + 1) begin
            store[index] = 16'h5aa5;
            reference_store[index] = 16'h5aa5;
        end
        repeat (4) @(negedge clk);
        init = 0;
        wait(controller.reset == 0);
        @(negedge clk); por_n = 1; run_competitors = 1;
        transaction(0, 1, 18'h00000, 16'h1234, 3, 0, 0);
        if (!FULL_WORD_ONLY) transaction(1, 1, 18'h00000, 16'h00ab, 1, 0, 0);
        transaction(0, 0, 18'h00000, 0, 3, FULL_WORD_ONLY ? 16'h1234 : 16'h12ab, 0);
        if (!FULL_WORD_ONLY) transaction(1, 1, 18'h00001, 16'hcd00, 2, 0, 0);
        transaction(0, 0, 18'h00000, 0, 3, FULL_WORD_ONLY ? 16'h1234 : 16'hcdab, 0);
        if (!FULL_WORD_ONLY) begin
            transaction(0, 0, 18'h00000, 0, 1, 16'hcdab, 0);
            transaction(1, 0, 18'h00001, 0, 2, 16'hcdab, 0);
        end
        transaction(1, 1, 18'h3fffe, 16'h9876, 3, 0, 1);
        if (!FULL_WORD_ONLY) transaction(0, 1, 18'h3ffff, 16'h5400, 2, 0, 1);
        transaction(1, 0, 18'h3fffe, 0, 3, FULL_WORD_ONLY ? 16'h9876 : 16'h5476, 0);
        transaction(0, 0, 18'h00000, 0, 3, FULL_WORD_ONLY ? 16'h1234 : 16'hcdab, 0);
        for (index = 0; index < 17; index = index + 1)
            transaction(0, 1, 18'b10 << index, 16'h8000 | 16'(index), 3, 0, 0);
        for (index = 0; index < 17; index = index + 1)
            transaction(1, 0, 18'b10 << index, 0, 3, 16'h8000 | 16'(index), 0);
        if (!FULL_WORD_ONLY) begin
            frontend_contention = 1;
            fork
                for (host_iteration = 0; host_iteration < 8; host_iteration = host_iteration + 1)
                    transaction(0, 1, 18'h00040, 16'h0090 + 16'(host_iteration), 1, 0, 0);
                for (card_iteration = 0; card_iteration < 8; card_iteration = card_iteration + 1)
                    transaction(1, 1, 18'h00041, 16'hd000 + (16'(card_iteration) << 8), 2, 0, 0);
            join
            frontend_contention = 0;
            if (contended_host != 8 || contended_card != 8) $fatal(1, "frontend contention lost progress");
            transaction(0, 0, 18'h00040, 0, 3, 16'hd797, 0);
        end
        wait(host_services == 6 && floppy_services == 6 && writeback_services == 6);
        repeat (30) @(negedge clk);

        // A serviced host level kept high still excludes the spare port.
        host_oe = 1;
        wait(cpu_done);
        repeat (8) @(negedge clk);
        starve = 1;
        ack_snapshot = backend_completed;
        fork
            transaction(1, 0, 18'h00000, 0, 3, FULL_WORD_ONLY ? 16'h1234 : 16'hcdab, 0);
            begin
                wait(native_req);
                repeat (512) begin
                    @(negedge clk);
                    starvation_ticks = starvation_ticks + 1;
                    if (!NATIVE_FAIR_MODE && (native_ack || mem_rsp_valid || backend_completed != ack_snapshot))
                        $fatal(1, "idle-only starvation control unexpectedly progressed");
                end
                if (NATIVE_FAIR_MODE && backend_completed == ack_snapshot)
                    $fatal(1, "fair native admission did not progress under held host request");
                host_oe = 0;
            end
        join
        starve = 0;
        repeat (10) @(negedge clk);
        if (accepted != completed || backend_accepted != backend_completed)
            $fatal(1, "completion counts differ");
        if (accepted != backend_accepted) $fatal(1, "byte access unexpectedly used extra backend operations");
        if (posted_acks != card_commits || early_acks != posted_acks || early_acks == 0)
            $fatal(1, "commit/posted control counts differ");
        if (refreshes <= 8) $fatal(1, "no runtime refresh exercised");
        if (!arb_drained || !adapter_drained || native_req || native_ack)
            $fatal(1, "final drain failed");
        for (index = 0; index < 131072; index = index + 1)
            if (store[index] !== reference_store[index])
                $fatal(1, "final store mismatch at word %h", index);
        $display("PASS native-byte-memory accepted=%0d completed=%0d backend=%0d commits=%0d early_posted_acks=%0d", accepted, completed, backend_completed, card_commits, early_acks);
        $display("host=%0d floppy=%0d refresh=%0d chip_reads=%0d chip_writes=%0d max_normal_ticks=%0d max_all_ticks=%0d", host_services, floppy_services, refreshes, chip_reads, chip_writes, max_normal_latency, max_latency);
        if (NATIVE_FAIR_MODE) $display("EXPECTED_NATIVE_PROGRESS held_host_ticks=%0d", starvation_ticks);
        else $display("EXPECTED_STARVATION held_host_ticks=%0d; card recovered after host release", starvation_ticks);
        $display("DQM low=%0d high=%0d word=%0d native_writeback=%0d", low_writes, high_writes, word_writes, writeback_services);
        $display("front_contention host=%0d card=%0d", contended_host, contended_card);
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

