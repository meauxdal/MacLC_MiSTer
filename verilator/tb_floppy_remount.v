/* tb_floppy_remount.v - regression bench for the floppy BLOCK-DEVICE mount
 * path across REMOUNTS. Real floppy_loader + floppy_sd_writer + eth_port_arb
 * (rtl/floppy_sd.v) against sim_ram.v, with the dl-port arbitration copied
 * from MacLC.sv (dl_grant/dl_locked, ~line 2790) and an hps_io slot model
 * (sd_ack per slot, ONE sd_buff_wr strobe broadcast to every slot).
 *
 * Reported on hardware: mount an 800K file, shut down, reset, mount the same
 * file again -> the Mac saw a blank "Untitled" volume and (writes On) the
 * file itself ended up blank. This bench asks: after ANY mount, does every
 * word of the SDRAM image region equal the mounted file, and does any
 * write-back ever carry a previous image's data into the new file?
 *
 * Scenarios (each ends with a full-region compare against the mounted file):
 *   S1  cold mount of A over a poisoned SDRAM
 *   S2  guest commits sectors (dirty SDRAM + writer queue), writer drains
 *   S3  mount B while the writer is mid-queue, with stray sd_buff_wr strobes
 *       from other slots during the load; no write may land in file B
 *   S4  core-style reset pulse (pll_locked) mid-load, then remount
 *   S5  remount of the SAME file after a guest-dirtied session (the report)
 *   S6  1.44 MB image then 800K image (size change)
 *   S7  second mount pulse WHILE a load is in flight (OSD double pick)
 *
 * Build + run (Verilator 5.x, from verilator/ ; in WSL):
 *   verilator --binary -j 0 -Wno-fatal -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
 *     -Wno-WIDTHCONCAT -Wno-CASEINCOMPLETE --timescale 1ns/1ps \
 *     --Mdir ../scratch/flp/obj_remount --top-module tb_floppy_remount \
 *     tb_floppy_remount.v sim_ram.v ../rtl/floppy_sd.v
 *   ../scratch/flp/obj_remount/Vtb_floppy_remount
 * PASS criterion: last line "RESULT: PASS", exit 0.
 */
`timescale 1ns/1ps

module tb_floppy_remount;

reg clk = 0;
always #5 clk = ~clk;

reg pll_locked = 0;                 // MacLC.sv: reset = !pll_locked_s

// ---------------------------------------------------------------- slot bus
localparam VDNUM = 7;
localparam FSLOT = 5;
reg  [VDNUM-1:0] sd_ack_v = 0;       // per-slot ack
wire sd_ack_f = sd_ack_v[FSLOT];
reg  [12:0] fl_addr = 0, st_addr = 0;
reg  [15:0] fl_dout = 0, st_dout = 0;
reg         fl_wr = 0, st_wr = 0;
wire [12:0] sd_buff_addr = sd_ack_f ? fl_addr : st_addr;
wire [15:0] sd_buff_dout = sd_ack_f ? fl_dout : st_dout;
wire        sd_buff_wr   = fl_wr | st_wr;           // ONE strobe, all slots

reg         img_mounted = 0;
reg  [63:0] img_size = 0;
reg         img_readonly = 0;

// ------------------------------------------------------------------ DUTs
wire [31:0] ldr_lba, sdw_lba;
wire        ldr_rd, sdw_wr;
wire [23:0] ldr_wr_addr;
wire [15:0] ldr_wr_data;
wire        ldr_wr_req;
wire        ldr_loading, ldr_done, ldr_ro, ldr_raw, ldr_dc42, ldr_mds;
wire [63:0] ldr_size;
wire  [7:0] ldr_fmt;
wire  [5:0] hdr_addr;
wire [15:0] hdr_data;
wire        ldr_wr_ack;

floppy_loader ldr (
	.clk_sys(clk), .reset(!pll_locked),
	.img_mounted(img_mounted), .img_size(img_size), .img_readonly(img_readonly),
	.sd_lba(ldr_lba), .sd_rd(ldr_rd), .sd_ack(sd_ack_f),
	.sd_buff_addr(sd_buff_addr), .sd_buff_dout(sd_buff_dout),
	.sd_buff_wr(sd_buff_wr),
	.base_addr(24'h600000),
	.wr_addr(ldr_wr_addr), .wr_data(ldr_wr_data), .wr_req(ldr_wr_req),
	.wr_ack(ldr_wr_ack),
	.loading(ldr_loading), .done(ldr_done), .size(ldr_size), .readonly(ldr_ro),
	.raw_img(ldr_raw), .is_dc42(ldr_dc42),
	.hdr_addr(hdr_addr), .hdr_data(hdr_data),
	.media_ds(ldr_mds), .dc42_fmt(ldr_fmt)
);

reg         write_ok = 1;
reg         wc_done = 0;
reg  [21:0] wc_commit_addr = 0;
wire        wr_busy;
wire        mem_req, mem_ack;
wire [23:0] mem_addr;
wire [15:0] mem_dout;
wire [15:0] sdw_din;
wire [63:0] file_bytes = ldr_size;
wire [12:0] file_blocks = file_bytes[21:9];

floppy_sd_writer #(.ACK_TIMEOUT_BITS(16)) wr (
	.clk(clk), .reset(!pll_locked), .img_mounted(img_mounted),
	.commit_done(wc_done), .commit_addr(wc_commit_addr),
	.write_ok(write_ok), .loader_busy(ldr_loading), .dc42(ldr_dc42),
	.flush_req(1'b0), .file_blocks(file_blocks), .file_tail(|file_bytes[8:0]),
	.img_base(24'h600000), .hdr_addr(hdr_addr), .hdr_data(hdr_data),
	.mem_req(mem_req), .mem_addr(mem_addr), .mem_ack(mem_ack), .mem_dout(mem_dout),
	.sd_lba(sdw_lba), .sd_wr(sdw_wr), .sd_ack(sd_ack_f),
	.sd_buff_addr_i(sd_buff_addr), .sd_buff_din(sdw_din), .busy(wr_busy)
);

wire        m_req, m_we, m_ack;
wire [23:0] m_addr;
wire [15:0] m_din, m_dout;
wire        a_ack;
wire [15:0] a_dout;
eth_port_arb arb (
	.clk(clk), .reset(!pll_locked),
	.a_req(1'b0), .a_we(1'b0), .a_addr(24'd0), .a_din(16'd0), .a_ack(a_ack), .a_dout(a_dout),
	.b_req(mem_req), .b_we(1'b0), .b_addr(mem_addr), .b_din(16'd0),
	.b_ack(mem_ack), .b_dout(mem_dout),
	.m_req(m_req), .m_we(m_we), .m_addr(m_addr), .m_din(m_din),
	.m_ack(m_ack), .m_dout(m_dout)
);

// the slot muxes exactly as MacLC.sv
wire [31:0] sd_lba = ldr_loading ? ldr_lba : sdw_lba;
wire        sd_rd  = ldr_rd;
wire        sd_wr  = ldr_loading ? 1'b0 : sdw_wr;

// ---------- dl-port arbitration, copied from MacLC.sv (~2790-2826) ----------
reg         wc_req = 0;
reg  [21:0] wc_addr = 0;
reg  [15:0] wc_data = 0;
wire        sdram_dl_ack;
wire        dio_download = 1'b0;
localparam DLG_LDR = 1'b0, DLG_WC = 1'b1;
reg  dl_grant, dl_locked;
always @(posedge clk) begin
	if (!pll_locked) begin
		dl_grant <= DLG_LDR; dl_locked <= 1'b0;
	end else if (dio_download) begin
		dl_locked <= 1'b0;
	end else if (dl_locked) begin
		if ((dl_grant == DLG_LDR && !ldr_wr_req) ||
		    (dl_grant == DLG_WC  && !wc_req))
			dl_locked <= 1'b0;
	end else if (ldr_wr_req) begin
		dl_grant <= DLG_LDR; dl_locked <= 1'b1;
	end else if (wc_req) begin
		dl_grant <= DLG_WC;  dl_locked <= 1'b1;
	end
end
wire dl_ldr_sel = dl_locked && (dl_grant == DLG_LDR) && !dio_download;
wire dl_wc_sel  = dl_locked && (dl_grant == DLG_WC)  && !dio_download;
wire [23:0] wc_word_addr = 24'h600000 + {3'd0, wc_addr[21:1]};
wire        dl_req_mux  = dl_wc_sel ? wc_req : ldr_wr_req;
wire [23:0] dl_addr_mux = dl_wc_sel ? wc_word_addr : ldr_wr_addr;
wire [15:0] dl_data_mux = dl_wc_sel ? wc_data : ldr_wr_data;
assign ldr_wr_ack = sdram_dl_ack && dl_ldr_sel;
wire   wc_ack     = sdram_dl_ack && dl_wc_sel;

// dl_slot: one bus slot in four, like dioBusControl
reg [3:0] slotdiv = 0;
reg       dl_slot = 0;
always @(posedge clk) begin
	slotdiv <= slotdiv + 4'd1;
	dl_slot <= (slotdiv[3:2] == 2'b10);
end

reg        sdram_dlreq_q = 0;
reg [23:0] sdram_dladdr_q = 0;
reg [15:0] sdram_dldin_q = 0;
always @(posedge clk) begin
	sdram_dlreq_q  <= dl_req_mux;
	sdram_dladdr_q <= dl_addr_mux;
	sdram_dldin_q  <= dl_data_mux;
end

wire        cpu_done;
wire [15:0] cpu_dout, dout;
sim_ram ram (
	.clk(clk), .reset(1'b0),
	.din(16'd0), .dout(dout), .addr(25'd0), .ds(2'b11), .oe(1'b0), .we(1'b0),
	.flp_win(1'b0), .flp_addr(24'd0), .flp_guard(1'b0),
	.dl_req(sdram_dlreq_q), .dl_slot(dl_slot), .dl_addr(sdram_dladdr_q),
	.dl_din(sdram_dldin_q), .dl_ack(sdram_dl_ack),
	.cpu_done(cpu_done), .cpu_dout(cpu_dout),
	.eth_req(m_req), .eth_we(m_we), .eth_addr(m_addr), .eth_din(m_din),
	.eth_ack(m_ack), .eth_dout(m_dout),
	.frame_count(32'd0)
);

// ------------------------------------------------------------ file store
// Four file slots of up to 1M words each
localparam FSTRIDE = 24'h100000;
reg [15:0] fm      [0:(4*FSTRIDE)-1];
reg [15:0] fm_orig [0:(4*FSTRIDE)-1];     // pristine copy for write detection
integer cur_file = 0;                      // which file hps_io has open
integer file_wr_count [0:3];
integer i, j;

function [15:0] patt(input integer f, input integer w);
	reg [15:0] x;
begin
	case (f)
	0: x = 16'hA000 ^ (w[15:0] * 16'd3);
	1: x = 16'h5001 ^ (w[15:0] * 16'd5);
	2: x = 16'h3C00 ^ (w[15:0] * 16'd7);
	default: x = 16'h0F0F ^ (w[15:0] * 16'd11);
	endcase
	patt = x ^ {7'd0, w[24:16]};
end
endfunction
function [15:0] bswap(input [15:0] d);
	bswap = {d[7:0], d[15:8]};
endfunction

// ----------------------------------------------------- hps_io slot model
integer rd_lat_min = 5, rd_lat_max = 40;
integer fl_lba;
reg     hps_busy = 0;
integer rd_blocks = 0, wr_blocks = 0;
integer seed = 32'h1badf00d;
reg     stray_en = 0;

always @(posedge clk) begin : hps
	integer k, lat, base;
	if (!hps_busy && sd_rd && !sd_ack_f) begin
		hps_busy = 1;
		fl_lba = sd_lba;
		lat = rd_lat_min + ({$random(seed)} % (rd_lat_max - rd_lat_min + 1));
		repeat (lat) @(posedge clk);
		sd_ack_v[FSLOT] = 1;
		repeat (3) @(posedge clk);
		base = cur_file * FSTRIDE + fl_lba * 256;
		for (k = 0; k < 256; k = k + 1) begin
			fl_addr = k; fl_dout = fm[base + k]; fl_wr = 1;
			@(posedge clk); fl_wr = 0;
			repeat (3) @(posedge clk);
		end
		repeat (4) @(posedge clk);
		sd_ack_v[FSLOT] = 0;
		rd_blocks = rd_blocks + 1;
		hps_busy = 0;
	end else if (!hps_busy && sd_wr && !sd_ack_f) begin
		hps_busy = 1;
		fl_lba = sd_lba;
		base = cur_file * FSTRIDE + fl_lba * 256;   // file open when taken
		repeat (3) @(posedge clk);
		sd_ack_v[FSLOT] = 1;
		repeat (2) @(posedge clk);
		for (k = 0; k < 256; k = k + 1) begin
			fl_addr = k;
			repeat (3) @(posedge clk);
			fm[base + k] = sdw_din;           // wire-order word
		end
		file_wr_count[cur_file] = file_wr_count[cur_file] + 1;
		repeat (2) @(posedge clk);
		sd_ack_v[FSLOT] = 0;
		wr_blocks = wr_blocks + 1;
		hps_busy = 0;
	end
end

// stray sd_buff_wr strobes from other slots (CD audio frame etc.): only while
// the floppy slot is NOT acked, random addr/data
always @(posedge clk) begin : stray
	if (stray_en && !sd_ack_f && ({$random(seed)} % 3 == 0)) begin
		st_wr <= 1; st_addr <= $random(seed); st_dout <= $random(seed);
	end else st_wr <= 0;
end

// ------------------------------------------------------------- helpers
integer errors = 0, checks = 0;

task wait_idle(input integer maxclk);
	integer g;
begin
	g = 0;
	while ((ldr_loading || wr_busy || hps_busy || ldr_wr_req || wc_req) && g < maxclk) begin
		@(posedge clk); g = g + 1;
	end
	repeat (200) @(posedge clk);
	if (g >= maxclk) begin errors = errors + 1; $display("FAIL: timeout waiting idle"); end
end
endtask

task mount(input integer f, input integer bytes);
begin
	@(negedge clk);
	cur_file = f; img_size = bytes; img_readonly = 0; img_mounted = 1;
	@(negedge clk); img_mounted = 0;
end
endtask

// compare SDRAM image region against file f (byte-swapped), nwords words
task check_image(input integer f, input integer nwords, input [127:0] tag);
	integer w, bad, first;
begin
	bad = 0; first = -1;
	for (w = 0; w < nwords; w = w + 1) begin
		if (ram.mem[24'h600000 + w] !== bswap(fm[f * FSTRIDE + w])) begin
			if (first < 0) first = w;
			bad = bad + 1;
		end
	end
	checks = checks + 1;
	if (bad != 0) begin
		errors = errors + 1;
		$display("FAIL [%0s]: %0d/%0d SDRAM words differ from file %0d (first word %0d: sdram=%04h want=%04h) -> STALE DATA",
		         tag, bad, nwords, f, first, ram.mem[24'h600000 + first],
		         bswap(fm[f * FSTRIDE + first]));
	end else $display("ok   [%0s]: SDRAM image == file %0d (%0d words)", tag, f, nwords);
end
endtask

// file f unchanged vs pristine (nwords words) and never written
task check_file_clean(input integer f, input integer nwords, input [127:0] tag);
	integer w, bad;
begin
	bad = 0;
	for (w = 0; w < nwords; w = w + 1)
		if (fm[f * FSTRIDE + w] !== fm_orig[f * FSTRIDE + w]) bad = bad + 1;
	checks = checks + 1;
	if (bad != 0 || file_wr_count[f] != 0) begin
		errors = errors + 1;
		$display("FAIL [%0s]: file %0d was modified: %0d words changed, %0d block writes -> WRITE-BACK INTO NEW FILE",
		         tag, f, bad, file_wr_count[f]);
	end else $display("ok   [%0s]: file %0d untouched (0 block writes)", tag, f);
end
endtask

// guest commit of sector s: 256 words through the wc port, then commit_done
task guest_commit(input integer s, input [15:0] salt);
	integer k, g;
begin
	for (k = 0; k < 256; k = k + 1) begin
		@(negedge clk);
		wc_addr = s * 512 + k * 2;
		wc_data = bswap(patt(3, s * 256 + k) ^ salt);
		wc_req = 1;
		g = 0;
		while (!wc_ack && g < 2000) begin @(posedge clk); g = g + 1; end
		if (g >= 2000) begin errors = errors + 1; $display("FAIL: wc ack timeout"); end
		@(negedge clk); wc_req = 0;
		repeat (2) @(posedge clk);
	end
	@(negedge clk); wc_commit_addr = s * 512; wc_done = 1;
	@(negedge clk); wc_done = 0;
end
endtask

localparam B800 = 819200, W800 = 409600, B1440 = 1474560, W1440 = 737280;

integer s2s, s2k, s2bad;
reg [15:0] s2salt;

initial begin
	for (i = 0; i < 4; i = i + 1) file_wr_count[i] = 0;
	// files: 0 = A (800K), 1 = B (800K), 2 = C (1.44M), 3 = D (800K)
	for (i = 0; i < W800; i = i + 1) begin
		fm[0*FSTRIDE + i] = patt(0, i);
		fm[1*FSTRIDE + i] = patt(1, i);
		fm[3*FSTRIDE + i] = patt(2, i);
	end
	for (i = 0; i < W1440; i = i + 1) fm[2*FSTRIDE + i] = patt(2, i + 7);
	for (i = 0; i < 4*FSTRIDE; i = i + 1) fm_orig[i] = fm[i];
	// poison the SDRAM image region
	for (i = 0; i < 24'h100000; i = i + 1) ram.mem[24'h600000 + i] = 16'hDEAD;

	repeat (10) @(posedge clk);
	pll_locked = 1;
	repeat (20) @(posedge clk);

	$display("=== S1: cold mount A over poisoned SDRAM ===");
	mount(0, B800); wait_idle(20000000);
	check_image(0, W800, "S1 A");

	$display("=== S2: guest commits sectors, writer drains into file A ===");
	guest_commit(2, 16'h1111); guest_commit(5, 16'h2222); guest_commit(1599, 16'h3333);
	wait_idle(20000000);
	for (j = 0; j < 3; j = j + 1) begin
		s2s    = (j == 0) ? 2 : (j == 1) ? 5 : 1599;
		s2salt = (j == 0) ? 16'h1111 : (j == 1) ? 16'h2222 : 16'h3333;
		s2bad  = 0;
		for (s2k = 0; s2k < 256; s2k = s2k + 1)
			if (fm[0*FSTRIDE + s2s*256 + s2k] !== (patt(3, s2s*256 + s2k) ^ s2salt))
				s2bad = s2bad + 1;
		checks = checks + 1;
		if (s2bad) begin
			errors = errors + 1;
			$display("FAIL [S2]: file A sector %0d has %0d bad words", s2s, s2bad);
		end else $display("ok   [S2]: file A sector %0d written back", s2s);
	end
	file_wr_count[0] = 0;
	for (i = 0; i < 4*FSTRIDE; i = i + 1) fm_orig[i] = fm[i];

	$display("=== S3: mount B while the writer is mid-queue, strays on ===");
	for (j = 0; j < 12; j = j + 1) guest_commit(100 + j, 16'h4000 + j);
	stray_en = 1;
	mount(1, B800);
	wait_idle(40000000);
	stray_en = 0;
	check_image(1, W800, "S3 B");
	check_file_clean(1, W800, "S3 fileB");

	$display("=== S4: reset pulse mid-load, then remount ===");
	mount(3, B800);
	repeat (30000) @(posedge clk);
	pll_locked = 0; repeat (5) @(posedge clk); pll_locked = 1; repeat (20) @(posedge clk);
	mount(3, B800); wait_idle(40000000);
	check_image(3, W800, "S4 D");

	$display("=== S5: guest dirties SDRAM, then remount of the SAME file ===");
	for (j = 0; j < 40; j = j + 1) guest_commit(300 + j, 16'h5000 + j);
	wait_idle(60000000);
	for (i = 0; i < 4*FSTRIDE; i = i + 1) fm_orig[i] = fm[i];   // those writes were real
	file_wr_count[3] = 0;
	pll_locked = 0; repeat (5) @(posedge clk); pll_locked = 1; repeat (20) @(posedge clk);
	stray_en = 1;
	mount(3, B800); wait_idle(40000000);
	stray_en = 0;
	check_image(3, W800, "S5 same file");
	check_file_clean(3, W800, "S5 fileD");

	$display("=== S6: 1.44MB then 800K ===");
	mount(2, B1440); wait_idle(80000000);
	check_image(2, W1440, "S6 1.44M");
	file_wr_count[1] = 0;
	mount(1, B800); wait_idle(40000000);
	check_image(1, W800, "S6 800K after 1.44M");

	$display("=== S7: second mount pulse while a load is in flight ===");
	mount(0, B800);
	repeat (50000) @(posedge clk);
	mount(1, B800);             // user picks again before the first finished
	wait_idle(60000000);
	check_image(1, W800, "S7 second mount");

	$display("");
	$display("checks=%0d errors=%0d  (rd_blocks=%0d wr_blocks=%0d)", checks, errors, rd_blocks, wr_blocks);
	if (errors == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
	$finish;
end

initial begin
	#4_000_000_000;
	$display("FAIL: global timeout");
	$display("RESULT: FAIL");
	$finish;
end

endmodule
