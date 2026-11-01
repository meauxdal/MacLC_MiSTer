`timescale 1ns/1ps
module tb_native_admission;
    parameter FAIR = 0;
    reg clk = 0;
    always #5 clk = !clk;
    reg [2:0] phase = 0;
    always @(posedge clk) phase <= phase + 1'b1;
    wire clk8 = phase[2];
    reg init = 1, oe = 0, we = 0, flp_win = 0, flp_guard = 0;
    reg dl_req = 0, dl_slot = 0, eth_req = 0, eth_we = 0;
    reg [23:0] eth_addr = 24'h540000;
    reg [15:0] eth_din = 0;
    wire [15:0] cpu_dout, dout, eth_dout;
    wire cpu_done, dl_ack, eth_ack;
    wire sd_clk, sd_cs, sd_we, sd_ras, sd_cas;
    wire [12:0] sd_addr;
    wire [1:0] sd_dqm, sd_ba;
    wire [15:0] sd_data;
    reg [15:0] chip_data = 0;
    reg [11:0] rows [0:3];
    reg [22:0] read_address, command_address;
    integer read_delay = 0, ticks = 0, native_stores = 0, download_stores = 0;
    integer cpu_services = 0, native_services = 0, floppy_services = 0, download_services = 0;
    integer refreshes = 0, last_refresh = 0, max_refresh_gap = 0, max_native_wait = 0;
    integer native_launch = 0, priority_checks = 0;
    integer contested_cpu = 0, contested_native = 0;
    reg measure_refresh = 0, stop_workers = 0;
    reg [15:0] private_ram [0:15];
    sdram #(.FAIR_NATIVE_ADMISSION(FAIR)) dut (
        .sd_clk(sd_clk), .sd_data(sd_data), .sd_data_in(chip_data), .sd_addr(sd_addr),
        .sd_dqm(sd_dqm), .sd_ba(sd_ba), .sd_cs(sd_cs), .sd_we(sd_we), .sd_ras(sd_ras), .sd_cas(sd_cas),
        .init(init), .clk_64(clk), .clk_8(clk8), .din(16'b0), .dout(dout), .addr(24'h000100),
        .ds(2'b11), .oe(oe), .we(we), .flp_win(flp_win), .flp_addr(24'h600100), .flp_guard(flp_guard),
        .dl_req(dl_req), .dl_slot(dl_slot), .dl_addr(24'h700000), .dl_din(16'h5678), .dl_ack(dl_ack),
        .eth_req(eth_req), .eth_we(eth_we), .eth_addr(eth_addr), .eth_din(eth_din), .eth_ack(eth_ack),
        .eth_dout(eth_dout), .cpu_done(cpu_done), .cpu_dout(cpu_dout)
    );
    task tick;
        begin @(posedge clk); #1; end
    endtask
    function [15:0] read_word(input [22:0] address);
        begin
            if (address == 23'h000100) read_word = 16'hBEEF;
            else if (address == 23'h600100) read_word = 16'hCAFE;
            else if (address >= 23'h540000 && address < 23'h540010) read_word = private_ram[address[3:0]];
            else $fatal(1, "unexpected SDRAM read %h", address);
        end
    endfunction
    always @(negedge clk) begin
        if (read_delay != 0) begin
            read_delay = read_delay - 1;
            if (read_delay == 0) chip_data <= read_word(read_address);
        end
        case ({sd_cs, sd_ras, sd_cas, sd_we})
            4'b0011: rows[sd_ba] = sd_addr[11:0];
            4'b0101: begin
                read_address = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                read_delay = 2;
            end
            4'b0100: begin
                command_address = {sd_addr[8], sd_ba, rows[sd_ba], sd_addr[7:0]};
                if (sd_dqm != 0) $fatal(1, "wholeword masks changed");
                if (command_address == 23'h700000) begin
                    if (sd_data != 16'h5678 || dut.src_cpu || dut.src_eth) $fatal(1, "download write/data ownership");
                    download_stores = download_stores + 1;
                end else if (command_address >= 23'h540000 && command_address < 23'h540010) begin
                    if (!dut.src_eth || dut.src_cpu) $fatal(1, "native write ownership");
                    private_ram[command_address[3:0]] = sd_data;
                    native_stores = native_stores + 1;
                end else $fatal(1, "unexpected SDRAM write %h", command_address);
            end
            4'b0001: if (dut.reset == 0) begin
                refreshes = refreshes + 1;
                if (measure_refresh && ticks - last_refresh > max_refresh_gap) max_refresh_gap = ticks - last_refresh;
                last_refresh = ticks;
            end
            default: ;
        endcase
    end
    reg check_grant = 0, expected_floppy, expected_download, expected_cpu, expected_native;
    always @(posedge clk) begin
        ticks <= ticks + 1;
        check_grant <= !init && dut.reset == 0 && !dut.seq_busy && !dut.ref_busy &&
                       (dut.req_flp || dut.req_dl || dut.req_cpu || dut.req_eth);
        expected_floppy <= dut.req_flp;
        expected_download <= !dut.req_flp && dut.req_dl;
        expected_cpu <= !dut.req_flp && !dut.req_dl && dut.grant_cpu;
        expected_native <= !dut.req_flp && !dut.req_dl && !dut.grant_cpu && dut.req_eth;
        if (!init && dut.reset == 0 && !dut.seq_busy && !dut.ref_busy &&
            !dut.req_flp && !dut.req_dl && dut.req_cpu && dut.req_eth) begin
            if (dut.grant_cpu) contested_cpu <= contested_cpu + 1;
            else contested_native <= contested_native + 1;
        end
    end
    always @(negedge clk) begin
        if (check_grant) begin
            priority_checks = priority_checks + 1;
            if (dut.src_cpu !== expected_cpu || dut.src_eth !== expected_native ||
                (expected_floppy && !dut.flp_served) || (expected_download && !dl_ack))
                $fatal(1, "mandatory priority or grant ownership mismatch");
        end
    end
    task cpu_worker;
        begin
            while (!stop_workers) begin
                oe = 1;
                wait(cpu_done);
                repeat (6) tick;
                if (cpu_dout !== 16'hBEEF) $fatal(1, "CPU private read corrupted");
                cpu_services = cpu_services + 1;
                oe = 0;
                repeat (2) tick;
            end
        end
    endtask
    task native_worker;
        integer n, before_stores;
        reg [15:0] wanted;
        begin
            for (n = 0; n < 64; n = n + 1) begin
                eth_we = !(n % 2);
                eth_addr = 24'h540000 + 24'(n / 2 % 16);
                eth_din = 16'hA63D ^ 16'(n / 2);
                wanted = eth_din;
                before_stores = native_stores;
                native_launch = ticks;
                eth_req = 1;
                wait(eth_ack);
                #1;
                if (ticks - native_launch > max_native_wait) max_native_wait = ticks - native_launch;
                if (eth_we && native_stores != before_stores) $fatal(1, "posted native ACK timing changed");
                if (!eth_we && eth_dout !== wanted) $fatal(1, "native private read corrupted");
                repeat (10) tick;
                if (eth_we && native_stores != before_stores + 1) $fatal(1, "native write not committed once");
                if (!eth_we && eth_dout !== wanted) $fatal(1, "native data clobbered while ACK held");
                native_services = native_services + 1;
                eth_req = 0;
                wait(!eth_ack);
                repeat (2) tick;
            end
            wait(stop_workers);
        end
    endtask
    task floppy_worker;
        begin
            while (!stop_workers) begin
                repeat (112) tick;
                flp_guard = 1;
                repeat (12) tick;
                flp_win = 1;
                repeat (12) tick;
                if (!dut.flp_served || dout !== 16'hCAFE) $fatal(1, "floppy window missed bounded deadline");
                floppy_services = floppy_services + 1;
                flp_win = 0;
                flp_guard = 0;
            end
        end
    endtask
    task download_worker;
        integer before_stores;
        begin
            while (!stop_workers) begin
                repeat (73) tick;
                before_stores = download_stores;
                dl_req = 1;
                dl_slot = 1;
                wait(dl_ack);
                repeat (10) tick;
                if (download_stores != before_stores + 1) $fatal(1, "download commit lost/duplicated");
                download_services = download_services + 1;
                dl_req = 0;
                dl_slot = 0;
                wait(!dl_ack);
            end
        end
    endtask
    integer i, before_native, before_cpu, bounded_refreshes;
    initial begin
        for (i = 0; i < 16; i = i + 1) private_ram[i] = 16'h1357;
        repeat (4) tick;
        init = 0;
        wait(dut.reset == 0);
        repeat (4) tick;
        // A completed host request remains asserted, blocking legacy admission.
        oe = 1;
        wait(cpu_done);
        repeat (8) tick;
        if (cpu_dout !== 16'hBEEF) $fatal(1, "initial CPU read");
        eth_req = 1;
        repeat (600) tick;
        if (FAIR == 0 && eth_ack) $fatal(1, "legacy starvation counterexample disappeared");
        if (FAIR != 0 && (!eth_ack || eth_dout !== 16'h1357)) $fatal(1, "served host level still denies native");
        oe = 0;
        wait(eth_ack);
        eth_req = 0;
        wait(!eth_ack);
        repeat (12) tick;
        if (FAIR == 0) begin
            $display("PASS legacy negative control: held completed OE denies native for600ticks; withdrawal releases it");
            $finish;
        end
        measure_refresh = 1;
        last_refresh = ticks;
        fork
            cpu_worker;
            native_worker;
            floppy_worker;
            download_worker;
            begin repeat (3000) tick; stop_workers = 1; end
        join
        repeat (20) tick;
        measure_refresh = 0;
        bounded_refreshes = refreshes;
        if (native_services != 64 || cpu_services < 20 || floppy_services < 10 || download_services < 10 ||
            refreshes < 3 || max_native_wait > 160 || max_refresh_gap > 550 || priority_checks < 50 ||
            contested_cpu == 0 || contested_native == 0)
            $fatal(1, "bounded progress/refresh failed cpu=%0d native=%0d floppy=%0d download=%0d refresh=%0d maxwait=%0d refgap=%0d", cpu_services, native_services, floppy_services, download_services, refreshes, max_native_wait, max_refresh_gap);
        // With an unbounded exclusion there is deliberately no finite service bound.
        flp_guard = 1;
        oe = 1;
        eth_req = 1;
        before_native = native_stores;
        before_cpu = cpu_services;
        repeat (1100) tick;
        if (cpu_done || eth_ack || native_stores != before_native || cpu_services != before_cpu || dut.ref_due < 480)
            $fatal(1, "unbounded guard did not exclude CPU/native and defer refresh");
        flp_guard = 0;
        tick;
        if (!dut.ref_busy || cpu_done || eth_ack)
            $fatal(1, "overdue refresh did not precede resumed CPU/native grants");
        wait(cpu_done && eth_ack);
        repeat (8) tick;
        if (cpu_dout !== 16'hBEEF || eth_dout !== private_ram[eth_addr[3:0]]) $fatal(1, "post-exclusion private data");
        oe = 0;
        eth_req = 0;
        repeat (10) tick;
        $display("PASS fair admission: CPU=%0d native=%0d floppy=%0d download=%0d refresh=%0d maxnativewait=%0d maxrefreshgap=%0d; unbounded guard denies1100ticks", cpu_services, native_services, floppy_services, download_services, bounded_refreshes, max_native_wait, max_refresh_gap);
        $display("contested CPU grants=%0d native grants=%0d", contested_cpu, contested_native);
        $finish;
    end
    initial begin #3000000; $fatal(1, "admission watchdog"); end
endmodule
