// tb_vram_ddr3.sv -- the DDR3 framebuffer (rtl/vram_ddr3.sv) under the real
// V8 scanout (rtl/maclc_v8_video.sv), sharing the real tv_ddr_arbiter with a
// 480i-style burst master on port a, against a DDR3 model with random
// waitrequest and read latency.
//
// Every word the V8 prefetch takes from the cache is checked against a model
// of what the CPU wrote, unless that word was written in the last stale_ps
// (the write queue's drain time is the design's only staleness).  Runs VGA
// 640x480 at every depth, the 12" 512x384 at 16 bpp, the portrait 640x870
// at 1 bpp and the IIe 560x384 at 4 bpp, with depth changes mid-stream.
//
// clk_mem 65 MHz and clk_sys 32.5 MHz are derived from one source (as the
// PLL does); clk_vid is unrelated.
`timescale 1ps/1ps
module tb_vram_ddr3;

localparam int  MEM_HALF = 7692;            // 65 MHz
time            stale_ps = 64'd20_000_000;  // 20 us; 1 ms under stress

// ---------------------------------------------------------------- clocks
logic clk_mem = 0, clk_sys = 0, clk_vid = 0;
int   vid_half = 19861;                     // 25.175 MHz
always #MEM_HALF clk_mem = ~clk_mem;
always @(posedge clk_mem) clk_sys <= ~clk_sys;
initial forever begin #vid_half clk_vid = ~clk_vid; end

// ---------------------------------------------------------------- V8
logic        rst_vid = 1;
logic  [2:0] video_mode = 3'd3;
logic  [3:0] monitor_id = 4'h6;
logic        iie_mode = 0;
wire  [17:0] v8_raddr, v8_base;
wire  [15:0] v8_rdata;
wire  [10:0] v8_wpl;
wire         v8_de, v8_vblank;

maclc_v8_video v8 (
    .clk_sys(clk_vid), .clk8_en_p(1'b0), .pix_ce(1'b1), .reset(rst_vid),
    .video_mode(video_mode), .monitor_id(monitor_id), .iie_mode(iie_mode),
    .test_bypass_vram(1'b0), .test_pattern_sel(2'd0),
    .hsync(), .vsync(), .hblank(), .vblank(v8_vblank),
    .vga_r(), .vga_g(), .vga_b(), .de(v8_de), .ce_pix(),
    .native_line_start(), .native_frame_start(), .native_width(), .native_height(),
    .palette_addr(), .palette_data(24'd0),
    .words_per_line(v8_wpl), .vram_raddr(v8_raddr), .vram_rdata(v8_rdata),
    .fetch_base(v8_base)
);

// ---------------------------------------------------------------- DUT
logic [17:0] cpu_addr = 0;
logic [15:0] cpu_din = 0;
logic  [1:0] cpu_be = 0;
logic        cpu_we = 0;
wire  [28:0] b_address;
wire   [7:0] b_burstcount, b_byteenable;
wire  [63:0] b_writedata, b_readdata;
wire         b_read, b_write, b_waitrequest, b_readdatavalid;
wire         wq_overflow;
wire   [9:0] wq_peak;

vram_ddr3 dut (
    .clk_sys(clk_sys), .cpu_addr(cpu_addr), .cpu_din(cpu_din), .cpu_be(cpu_be), .cpu_we(cpu_we),
    .clk_vid(clk_vid), .reset_vid(rst_vid), .vid_base(v8_base), .vid_wpl(v8_wpl),
    .vid_raddr(v8_raddr), .vid_rdata(v8_rdata),
    .clk_mem(clk_mem),
    .ddr_address(b_address), .ddr_burstcount(b_burstcount), .ddr_writedata(b_writedata),
    .ddr_byteenable(b_byteenable), .ddr_read(b_read), .ddr_write(b_write),
    .ddr_waitrequest(b_waitrequest), .ddr_readdatavalid(b_readdatavalid), .ddr_readdata(b_readdata),
    .wq_overflow(wq_overflow), .wq_peak(wq_peak)
);

// ---------------------------------------------------------------- 480i-style master (port a)
logic [28:0] a_address = 0;
logic  [7:0] a_burstcount = 1;
logic [63:0] a_writedata = 0;
logic        a_read = 0, a_write = 0;
wire         a_waitrequest, a_readdatavalid;
wire  [63:0] a_readdata;
// Bandwidth in beats per 1000 clk_mem (65 MHz): 385 = 25M beats/s, about
// what the 480i store moves (32-beat capture writes, 128-beat line reads
// after tv_ddram_bridge splits them).
int          tv_rate = 385;
int          tv_bucket = 0;

wire  [28:0] address;
wire   [7:0] burstcount, byteenable;
wire  [63:0] writedata;
wire         read, write;
logic        waitrequest = 1, readdatavalid = 0;
logic [63:0] readdata = 0;

tv_ddr_arbiter #(.DW(64), .AW(29)) arb (
    .clk(clk_mem), .inhibit(1'b0),
    .a_address(a_address), .a_burstcount(a_burstcount), .a_writedata(a_writedata),
    .a_byteenable(8'hFF), .a_read(a_read), .a_write(a_write),
    .a_waitrequest(a_waitrequest), .a_readdatavalid(a_readdatavalid), .a_readdata(a_readdata),
    .b_address(b_address), .b_burstcount(b_burstcount), .b_writedata(b_writedata),
    .b_byteenable(b_byteenable), .b_read(b_read), .b_write(b_write),
    .b_waitrequest(b_waitrequest), .b_readdatavalid(b_readdatavalid), .b_readdata(b_readdata),
    .address(address), .burstcount(burstcount), .writedata(writedata), .byteenable(byteenable),
    .read(read), .write(write), .waitrequest(waitrequest), .readdatavalid(readdatavalid),
    .readdata(readdata)
);

int tv_beats = 0;
int left = 0, wleft = 0;
always @(posedge clk_mem) begin : tv_master
    if (a_read && !a_waitrequest) a_read <= 0;
    if (a_readdatavalid) begin left--; tv_beats++; end
    if (a_write && !a_waitrequest) begin
        tv_beats++;
        a_writedata <= {$urandom, $urandom};
        if (wleft == 1) a_write <= 0;
        wleft--;
    end
    if (tv_bucket < 200000) tv_bucket += tv_rate;
    if (!a_read && !a_write && left == 0 && wleft == 0 && tv_bucket >= 128000) begin
        logic [7:0] n;
        n = ($urandom % 3 == 0) ? 8'd128 : 8'd32;
        tv_bucket -= int'(n) * 1000;
        a_address    <= 29'h0430_0000 + ($urandom % 29'h7_0000);
        a_burstcount <= n;
        if ($urandom % 2) begin
            a_read <= 1;
            left    = int'(n);
        end else begin
            a_write     <= 1;
            a_writedata <= {$urandom, $urandom};
            wleft       = int'(n);
        end
    end
end

// ---------------------------------------------------------------- DDR3 model
logic [63:0] mem [logic [28:0]];
typedef struct { logic [63:0] d; int due; } beat_t;
beat_t       rq[$];
int          cyc = 0;
int          wr_left = 0;
logic [28:0] wr_addr;
int          wait_pct = 30;

function automatic logic [63:0] rd64(input logic [28:0] a);
    return mem.exists(a) ? mem[a] : 64'd0;
endfunction

always @(posedge clk_mem) begin : ddr_model
    cyc++;
    // accept commands while waitrequest is low (sampled this edge)
    if (!waitrequest && read) begin
        int lat;
        lat = 8 + $urandom % 40;
        for (int i = 0; i < int'(burstcount); i++) begin
            beat_t b;
            b.d = rd64(address + 29'(i));   // snapshot at accept: in order
            b.due = cyc + lat + i;
            rq.push_back(b);
        end
    end
    if (!waitrequest && write) begin
        logic [28:0] a;
        logic [63:0] v;
        if (wr_left == 0) begin a = address; wr_left = int'(burstcount); end
        else a = wr_addr;
        v = rd64(a);
        for (int k = 0; k < 8; k++) if (byteenable[k]) v[8*k +: 8] = writedata[8*k +: 8];
        mem[a] = v;
        wr_addr = a + 1;
        wr_left--;
    end
    readdatavalid <= 0;
    if (rq.size() != 0 && rq[0].due <= cyc && ($urandom % 100) >= 10) begin
        readdatavalid <= 1;
        readdata      <= rq[0].d;
        void'(rq.pop_front());
    end
    waitrequest <= ($urandom % 100) < wait_pct;
end

int vram_wr = 0, vram_rd = 0;
always @(posedge clk_mem) begin
    if (b_write && !b_waitrequest) vram_wr++;
    if (b_readdatavalid) vram_rd++;
end

// ---------------------------------------------------------------- CPU writes
logic [15:0] model [0:262143];
time         wtime [0:262143];
int          wr_gap_min = 6, wr_gap_max = 24, writes_on = 0;
int          n_writes = 0;
int          active_lines = 480;
initial for (int i = 0; i < 262144; i++) begin model[i] = 0; wtime[i] = 0; end

int gap = 0;
int run_left = 0;
logic [17:0] run_addr = 0;
int scatter_pct = 25;      // writes that land at a random address
always @(posedge clk_sys) begin : cpu
    cpu_we <= 0;
    if (writes_on != 0) begin
        if (gap > 0) gap--;
        else begin
            int span;
            logic [17:0] a;
            logic [15:0] d;
            logic  [1:0] be;
            span = int'(v8_wpl) * active_lines;
            if (span < 1) span = 1;
            if (run_left == 0) begin
                run_addr = 18'($urandom % span);
                run_left = 1 + $urandom % 256;
            end
            if (($urandom % 100) < scatter_pct) a = 18'($urandom % span);
            else begin
                a = run_addr;
                run_addr = (int'(run_addr) + 1 >= span) ? 18'd0 : run_addr + 1;
                run_left--;
            end
            d  = 16'($urandom);
            be = 2'(1 + $urandom % 3);
            cpu_addr <= a; cpu_din <= d; cpu_be <= be; cpu_we <= 1;
            if (be[0]) model[a][7:0]  = d[7:0];
            if (be[1]) model[a][15:8] = d[15:8];
            wtime[a] = $time;
            n_writes++;
            gap = wr_gap_min + $urandom % (wr_gap_max - wr_gap_min + 1);
        end
    end
end

// ---------------------------------------------------------------- checker
logic [17:0] prev_raddr = 0;
int  checks = 0, skipped = 0, errors = 0;
bit  check_on = 0;
always @(posedge clk_vid) begin : scan_check
    // only fetches that reach the screen: active lines, and the last
    // vblank line (line 0; the V8 refetches it on every vblank line)
    if (check_on && v8.fetch_pend &&
        (!v8.vblank_c || v8.v_count == v8.v_total - 10'd1)) begin
        if (wtime[prev_raddr] != 0 && $time - wtime[prev_raddr] < stale_ps) skipped++;
        else begin
            checks++;
            if (v8_rdata !== model[prev_raddr]) begin
                errors++;
                if (errors <= 20)
                    $display("MISMATCH t=%0t addr=%05h got=%04h want=%04h base=%05h wpl=%0d",
                             $time, prev_raddr, v8_rdata, model[prev_raddr], v8_base, v8_wpl);
            end
        end
    end
    prev_raddr <= v8_raddr;
end

// count V8 frames
int frames = 0;
logic vbl_d = 0;
always @(posedge clk_vid) begin vbl_d <= v8_vblank; if (v8_vblank && !vbl_d) frames++; end

task automatic wait_frames(input int n);
    int f0 = frames;
    wait (frames >= f0 + n);
endtask

// one configuration: settle (no checks) for 2 frames, then check `n` frames
task automatic run_mode(input string name, input logic [3:0] mon, input logic [2:0] mode,
                        input logic iie, input int half, input int lines, input int n);
    int c0 = checks, e0 = errors, s0 = skipped;
    check_on   = 0;
    monitor_id = mon; video_mode = mode; iie_mode = iie; vid_half = half;
    active_lines = lines;
    wait_frames(2);
    check_on = 1;
    wait_frames(n);
    $display("%-28s wpl=%0d checks=%0d skipped=%0d errors=%0d writes=%0d wq_peak=%0d tv_beats=%0d vram_wr=%0d vram_rd=%0d",
             name, v8_wpl, checks - c0, skipped - s0, errors - e0, n_writes, wq_peak, tv_beats, vram_wr, vram_rd);
endtask

initial begin
    repeat (20) @(posedge clk_vid);
    rst_vid = 0;
    writes_on = 1;
    run_mode("VGA 640x480 8bpp",      4'h6, 3'd3, 0, 19861, 480, 3);
    run_mode("VGA 640x480 1bpp",      4'h6, 3'd0, 0, 19861, 480, 2);
    run_mode("VGA 640x480 2bpp",      4'h6, 3'd1, 0, 19861, 480, 2);
    run_mode("VGA 640x480 4bpp",      4'h6, 3'd2, 0, 19861, 480, 2);
    run_mode("12in 512x384 16bpp",    4'h2, 3'd4, 0, 31921, 384, 3);
    run_mode("12in 512x384 8bpp",     4'h2, 3'd3, 0, 31921, 384, 2);
    run_mode("portrait 640x870 1bpp", 4'h1, 3'd0, 0,  8512, 870, 2);
    run_mode("IIe 560x384 4bpp 12in", 4'h2, 3'd2, 1, 29083, 384, 2);
    // heavy: 480i master at 29M beats/s, DDR waitrequest 40 % (39M beats/s
    // left), CPU writes every 6-10 clk_sys (about 4M/s, a 16 MHz 68020's
    // ceiling), a quarter of them scattered
    tv_rate = 450; wait_pct = 40; wr_gap_min = 5; wr_gap_max = 9;
    stale_ps = 64'd1_000_000_000;   // a 400-entry backlog drains slowly
    run_mode("stress 512x384 16bpp",  4'h2, 3'd4, 0, 31921, 384, 2);
    tv_rate = 385; wait_pct = 30; wr_gap_min = 6; wr_gap_max = 24;
    stale_ps = 64'd20_000_000;
    run_mode("after stress VGA 8bpp", 4'h6, 3'd3, 0, 19861, 480, 2);
    // quiet: writes stop, everything must match exactly, nothing skipped
    writes_on = 0;
    run_mode("quiet VGA 8bpp",        4'h6, 3'd3, 0, 19861, 480, 2);
    $display("TOTAL checks=%0d skipped=%0d errors=%0d overflow=%0d wq_peak=%0d",
             checks, skipped, errors, wq_overflow, wq_peak);
    if (errors != 0 || wq_overflow || checks == 0) begin
        $display("FAIL");
        $fatal(1);
    end
    $display("PASS");
    $finish;
end

endmodule
