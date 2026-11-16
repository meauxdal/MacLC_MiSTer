/* tb_floppy_write.v - END-TO-END guest floppy WRITE path (GCR 800K).
 *
 *   IWM data-register writes (swim.v) -> floppy.v write pacing ->
 *   floppy_track_decoder -> floppy_write_committer -> dl-port arbitration
 *   (copied from MacLC.sv ~2790) -> sim_ram SDRAM -> floppy_sd_writer ->
 *   hps_io slot model -> file model.
 *
 * The guest is emulated the way the Sony driver drives the hardware: seek
 * with the DIRTN/STEP drive registers, park the phase lines on RDDATA0/1 for
 * the head select, enter write mode (q7) and push a complete GCR data field
 * (sync, D5 AA AD, sector byte, 12 tag + 512 data bytes in 6&2 groups,
 * checksum, DE AA) through the data register, one byte per handshake. The
 * bench has its OWN GCR encoder, independent of the RTL's.
 *
 * Golden model: a byte array of the whole 800K file. Every guest write
 * updates exactly one 512-byte block (cylinder-major layout, computed here by
 * an independent loop). After each scenario the bench checks EVERY word of
 * the SDRAM image AND every word of the file against the golden model, so a
 * sector landing at a wrong offset, or any unwritten sector changing, fails.
 *
 * Scenarios:
 *   W1  writes in all five speed zones, both sides, seeks in both directions
 *   W2  write immediately after a seek (no settle) and side-flip sequences
 *   W3  write-protect toggled between writes (a refused write must not land
 *       anywhere; the driver never learns, so the bench keeps going)
 *   W4  head-select flips while a data field is in flight (must not move
 *       any OTHER sector)
 *   W5  remount of the same file right after queued writes drained, then
 *       writes again
 * The 800K image carries a valid HFS MDB so the loader's sidedness sniff
 * (media_ds) is exercised exactly as on hardware.
 *
 * Build + run (Verilator 5.x, from verilator/ ; in WSL):
 *   verilator --binary -j 0 -Wno-fatal -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
 *     -Wno-WIDTHCONCAT -Wno-CASEINCOMPLETE -Wno-MULTIDRIVEN \
 *     --timescale 1ns/1ps +define+SIMULATION -I../rtl \
 *     --Mdir ../scratch/flp/obj_write --top-module tb_floppy_write \
 *     tb_floppy_write.v sim_ram.v ../rtl/swim.v ../rtl/floppy.v \
 *     ../rtl/mfm_track_encoder.v ../rtl/floppy_track_encoder.v \
 *     ../rtl/floppy_track_decoder.v ../rtl/mfm_write_decoder.v \
 *     ../rtl/floppy_sd.v
 *   ../scratch/flp/obj_write/Vtb_floppy_write
 * (add the other rtl files swim.v pulls in if the link complains)
 * PASS criterion: last line "RESULT: PASS", exit 0.
 */
`timescale 1ns/1ps

module tb_floppy_write;

reg clk = 0;
always #15.625 clk = ~clk;          // 32 MHz

reg [1:0] phase = 0;
always @(posedge clk) phase <= phase + 1'b1;
wire cep = (phase == 2'd0);
wire cen = (phase == 2'd2);

reg _reset = 0;
reg pll_locked = 0;

// ------------------------------------------------------------ hps slot bus
localparam VDNUM = 7;
localparam FSLOT = 5;
reg  [VDNUM-1:0] sd_ack_v = 0;
wire sd_ack_f = sd_ack_v[FSLOT];
reg  [12:0] fl_addr = 0, st_addr = 0;
reg  [15:0] fl_dout = 0, st_dout = 0;
reg         fl_wr = 0, st_wr = 0;
wire [12:0] sd_buff_addr = sd_ack_f ? fl_addr : st_addr;
wire [15:0] sd_buff_dout = sd_ack_f ? fl_dout : st_dout;
wire        sd_buff_wr   = fl_wr | st_wr;

reg         img_mounted = 0;
reg  [63:0] img_size = 0;

// ------------------------------------------------------------------- DUTs
wire [31:0] ldr_lba, sdw_lba;
wire        ldr_rd, sdw_wr;
wire [23:0] ldr_wr_addr;
wire [15:0] ldr_wr_data;
wire        ldr_wr_req, ldr_wr_ack;
wire        ldr_loading, ldr_done, ldr_ro, ldr_raw, ldr_dc42, ldr_mds;
wire [63:0] ldr_size;
wire  [7:0] ldr_fmt;
wire  [5:0] hdr_addr;
wire [15:0] hdr_data;

floppy_loader ldr (
	.clk_sys(clk), .reset(!pll_locked),
	.img_mounted(img_mounted), .img_size(img_size), .img_readonly(1'b0),
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

// OSD "Floppy writes" and the resulting write-protect, as MacLC.sv
reg         wr_osd = 1;
wire        flp_wp = ~wr_osd || ldr_ro;

wire        wc_done;
wire [21:0] wc_commit_addr;
wire        wr_busy;
wire        mem_req, mem_ack;
wire [23:0] mem_addr;
wire [15:0] mem_dout;
wire [15:0] sdw_din;
wire [63:0] file_bytes = ldr_size;

floppy_sd_writer #(.ACK_TIMEOUT_BITS(16)) wr (
	.clk(clk), .reset(!pll_locked), .img_mounted(img_mounted),
	.commit_done(wc_done), .commit_addr(wc_commit_addr),
	.write_ok(~flp_wp), .loader_busy(ldr_loading), .dc42(ldr_dc42),
	.flush_req(1'b0), .file_blocks(file_bytes[21:9]), .file_tail(|file_bytes[8:0]),
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

wire [31:0] sd_lba = ldr_loading ? ldr_lba : sdw_lba;
wire        sd_rd  = ldr_rd;
wire        sd_wr  = ldr_loading ? 1'b0 : sdw_wr;

// ---------- dl-port arbitration, copied from MacLC.sv (~2790-2826) ----------
wire        wc_req, wc_ack;
wire [21:0] wc_addr;
wire [15:0] wc_data;
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
assign wc_ack     = sdram_dl_ack && dl_wc_sel;

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
wire [15:0] cpu_dout, ram_dout;
sim_ram ram (
	.clk(clk), .reset(1'b0),
	.din(16'd0), .dout(ram_dout), .addr(25'd0), .ds(2'b11), .oe(1'b0), .we(1'b0),
	.flp_win(1'b0), .flp_addr(24'd0), .flp_guard(1'b0),
	.dl_req(sdram_dlreq_q), .dl_slot(dl_slot), .dl_addr(sdram_dladdr_q),
	.dl_din(sdram_dldin_q), .dl_ack(sdram_dl_ack),
	.cpu_done(cpu_done), .cpu_dout(cpu_dout),
	.eth_req(m_req), .eth_we(m_we), .eth_addr(m_addr), .eth_din(m_din),
	.eth_ack(m_ack), .eth_dout(m_dout),
	.frame_count(32'd0)
);

// ------------------------------------------------- the guest-facing SWIM
reg        selectSWIM = 0;
reg        _cpuRW = 1;
reg        _cpuUDS = 1;
reg [15:0] dataIn = 0;
reg [3:0]  cpuAddrRegHi = 0;
reg        SEL = 0;
reg        driveSel = 1;
wire [15:0] dataOut;

// drive-present, as MacLC.sv: down at the mount pulse, up after `done`
reg flp_ins = 0;
always @(posedge clk) begin
	if (img_mounted) flp_ins <= 1'b0;
	else if (ldr_done) flp_ins <= 1'b1;
end
wire ds800 = (ldr_size == 64'd819200);
reg  ms_en = 1;

// SDRAM-served read data for the encoder: byte at image byte address
wire [21:0] dskReadAddrInt, dskReadAddrExt;
reg         dskReadAckInt = 0;
wire [15:0] rd_word = ram.mem[24'h600000 + dskReadAddrInt[21:1]];
wire [7:0]  dskReadData = dskReadAddrInt[0] ? rd_word[7:0] : rd_word[15:8];
integer ack_div = 0;
always @(posedge clk) if (cen) begin
	ack_div <= ack_div + 1;
	if (ack_div >= 8) begin ack_div <= 0; dskReadAckInt <= 1'b1; end
	else dskReadAckInt <= 1'b0;
end

wire [6:0]  dbg_track;
wire        dbg_side;

swim dut (
	.clk(clk), .cep(cep), .cen(cen), ._reset(_reset),
	.selectSWIM(selectSWIM), ._cpuRW(_cpuRW), ._cpuUDS(_cpuUDS),
	.dataIn(dataIn), .cpuAddrRegHi(cpuAddrRegHi), .SEL(SEL),
	.driveSel(driveSel), .dataOut(dataOut),
	.insertDisk({1'b0, flp_ins}),
	.writeProtect({1'b1, flp_wp}),
	.wrSdAddr(wc_addr), .wrSdData(wc_data), .wrSdReq(wc_req), .wrSdAck(wc_ack),
	.wrCommitDone(wc_done), .wrCommitAddr(wc_commit_addr),
	.wrSdBufAddr(), .wrSdBufData(), .wrSdBufWr(),
	.diskSides({1'b0, ds800}),
	.mediaSides({1'b1, ldr_mds & ms_en}),   // +ms=0: negative control
	.diskMFM(2'b00), .diskHD(2'b00),
	.diskEject(), .diskMotor(), .diskAct(),
	.dskReadAddrInt(dskReadAddrInt), .dskReadAckInt(dskReadAckInt),
	.dskReadAddrExt(dskReadAddrExt), .dskReadAckExt(1'b0),
	.dskReadData(dskReadData),
	.dbg_ism_flpe(),
	.dbg_flp_byte_cnt(), .dbg_flp_miss_cnt(), .dbg_flp_disk_data(),
	.dbg_flp_track(dbg_track), .dbg_flp_side(dbg_side), .dbg_flp_step_cnt(),
	.dbg_iwm_latch(), .dbg_flp_byte_stb(), .dbg_flp_raw(),
	.dbg_ism_state(),
	.dbg_flp_strb_cnt(), .dbg_flp_strb_en_cnt(), .dbg_flp_strb_last(),
	.dbg_flp_rej_step(), .dbg_flp_status(), .dbg_flp_gcr_addr(),
	.dbg_ism_verdict(), .dbg_ism_unrlatch(),
	.dbg_ism_scan(), .dbg_mfm_stall()
);

// ------------------------------------------------------------ file store
localparam FBYTES = 819200, FWORDS = 409600;
reg [15:0] fm [0:FWORDS-1];          // the file, hps_io wire order {odd,even}
reg [7:0]  gold [0:FBYTES-1];        // what the file SHOULD hold now
integer file_wr_blocks = 0;
integer seed = 32'h51a7e5;
integer i, j;

// hps_io slot model (reads serve the loader, writes land in fm)
reg     hps_busy = 0;
always @(posedge clk) begin : hps
	integer k, lat, base, lba;
	if (!hps_busy && sd_rd && !sd_ack_f) begin
		hps_busy = 1;
		lba = sd_lba;
		lat = 5 + ({$random(seed)} % 30);
		repeat (lat) @(posedge clk);
		sd_ack_v[FSLOT] = 1;
		repeat (3) @(posedge clk);
		for (k = 0; k < 256; k = k + 1) begin
			fl_addr = k; fl_dout = fm[lba * 256 + k]; fl_wr = 1;
			@(posedge clk); fl_wr = 0;
			repeat (3) @(posedge clk);
		end
		repeat (4) @(posedge clk);
		sd_ack_v[FSLOT] = 0;
		hps_busy = 0;
	end else if (!hps_busy && sd_wr && !sd_ack_f) begin
		hps_busy = 1;
		lba = sd_lba;
		repeat (3) @(posedge clk);
		sd_ack_v[FSLOT] = 1;
		repeat (2) @(posedge clk);
		for (k = 0; k < 256; k = k + 1) begin
			fl_addr = k;
			repeat (3) @(posedge clk);
			fm[lba * 256 + k] = sdw_din;
		end
		file_wr_blocks = file_wr_blocks + 1;
		repeat (2) @(posedge clk);
		sd_ack_v[FSLOT] = 0;
		hps_busy = 0;
	end
end

// ---------------------------------------------- CPU-side bus tasks (E-paced)
integer acclen = 40, pollgap = 40;

task swim_wr(input [3:0] a, input [7:0] d);
begin
	@(posedge clk);
	cpuAddrRegHi <= a; dataIn <= {8'h00, d}; _cpuRW <= 1'b0;
	selectSWIM <= 1'b1; _cpuUDS <= 1'b0;
	repeat (acclen) @(posedge clk);
	selectSWIM <= 1'b0; _cpuUDS <= 1'b1; _cpuRW <= 1'b1;
	repeat (10) @(posedge clk);
end
endtask

task swim_rd(input [3:0] a, output [7:0] d);
begin
	@(posedge clk);
	cpuAddrRegHi <= a; _cpuRW <= 1'b1;
	selectSWIM <= 1'b1; _cpuUDS <= 1'b0;
	repeat (acclen) @(posedge clk);
	d = dataOut[15:8];
	selectSWIM <= 1'b0; _cpuUDS <= 1'b1;
	repeat (4) @(posedge clk);
	repeat (pollgap) @(posedge clk);
end
endtask

// drive-register write via the phase lines (SEL low), as tb_gcr_read.v
task drive_wr(input rca1, input rca0, input dat);
begin
	swim_wr(rca1 ? 4'd3 : 4'd2, 8'h00);
	swim_wr(rca0 ? 4'd1 : 4'd0, 8'h00);
	swim_wr(dat  ? 4'd5 : 4'd4, 8'h00);
	swim_wr(4'd7, 8'h00);
	swim_wr(4'd6, 8'h00);
	repeat (200) @(posedge clk);
end
endtask

integer cur_track = 0;
reg     cur_side  = 0;

// head select: park the phases on RDDATA0/1 = {ca2,ca1,ca0,SEL}=100,side
task park_head(input side);
begin
	swim_wr(4'd2, 8'h00);
	swim_wr(4'd0, 8'h00);
	SEL = side;
	swim_wr(4'd5, 8'h00);
	cur_side = side;
	repeat (100) @(posedge clk);
end
endtask

// seek to track t from cur_track in the right direction, then park on side
task seek(input integer t, input side, input integer settle);
	integer n;
begin
	SEL = 1'b0;
	swim_wr(4'd4, 8'h00);              // ca2 = 0 (leave the sense address)
	if (t > cur_track) begin
		drive_wr(1'b0, 1'b0, 1'b0);      // DIRTN = 0: toward 79
		for (n = cur_track; n < t; n = n + 1) drive_wr(1'b0, 1'b1, 1'b0);
	end else if (t < cur_track) begin
		drive_wr(1'b0, 1'b0, 1'b1);      // DIRTN = 1: toward 0
		for (n = cur_track; n > t; n = n - 1) drive_wr(1'b0, 1'b1, 1'b0);
	end
	cur_track = t;
	park_head(side);
	repeat (settle) @(posedge clk);
	if (dbg_track !== t[6:0] || dbg_side !== side) begin
		errors = errors + 1;
		$display("FAIL: seek wanted trk %0d side %0d, drive is at %0d/%0d",
		         t, side, dbg_track, dbg_side);
	end
end
endtask

// ------------------------------------------------------- independent layout
function integer spt_of(input integer c);
	spt_of = (c < 16) ? 12 : (c < 32) ? 11 : (c < 48) ? 10 : (c < 64) ? 9 : 8;
endfunction
function integer blk_of(input integer c, input integer s, input integer n);
	integer k, b;
begin
	b = 0;
	for (k = 0; k < c; k = k + 1) b = b + 2 * spt_of(k);
	blk_of = b + s * spt_of(c) + n;
end
endfunction

// ------------------------------------------------------- GCR data-field encoder
reg [7:0] gt [0:63];
reg [7:0] pay [0:511];
reg [7:0] encb [0:1023];
integer   encn;

task enc_push(input [7:0] b);
begin encb[encn] = b; encn = encn + 1; end
endtask

task build_field(input integer n);
	integer g, nb, q;
	reg [7:0] c1, c2, c3, rc, d0, d1, d2, dec0, dec1, dec2;
	reg [8:0] s3, s2;
	reg [7:0] c3n, c2n, c1n;
	reg [5:0] tops;
begin
	encn = 0;
	for (q = 0; q < 4; q = q + 1) enc_push(8'hFF);
	enc_push(8'hD5); enc_push(8'hAA); enc_push(8'hAD);
	enc_push(gt[n[5:0]]);
	c1 = 0; c2 = 0; c3 = 0;
	for (g = 0; g < 175; g = g + 1) begin
		nb = (g == 174) ? 2 : 3;
		q  = g * 3;                       // payload index into tag(12)+data(512)
		d0 = (q     < 12) ? 8'h00 : pay[q - 12];
		d1 = (q + 1 < 12) ? 8'h00 : pay[q + 1 - 12];
		d2 = (q + 2 < 12) ? 8'h00 : pay[q + 2 - 12];
		rc   = {c1[6:0], c1[7]};
		dec0 = d0 ^ rc;
		s3   = {1'b0, c3} + {1'b0, d0} + {8'd0, c1[7]};
		c3n  = s3[7:0];
		dec1 = d1 ^ c3n;
		s2   = {1'b0, c2} + {1'b0, d1} + {8'd0, s3[8]};
		c2n  = s2[7:0];
		if (nb == 3) begin
			dec2 = d2 ^ c2n;
			c1n  = rc + d2 + {7'd0, s2[8]};
		end else begin
			dec2 = 8'h00;
			c1n  = rc;
		end
		tops = {dec0[7:6], dec1[7:6], dec2[7:6]};
		enc_push(gt[tops]);
		enc_push(gt[dec0[5:0]]);
		enc_push(gt[dec1[5:0]]);
		if (nb == 3) enc_push(gt[dec2[5:0]]);
		c1 = c1n; c2 = c2n; c3 = c3n;
	end
	enc_push(gt[{c3[7:6], c2[7:6], c1[7:6]}]);
	enc_push(gt[c3[5:0]]);
	enc_push(gt[c2[5:0]]);
	enc_push(gt[c1[5:0]]);
	enc_push(8'hDE); enc_push(8'hAA); enc_push(8'hFF);
end
endtask

// ------------------------------------------------------- guest-style write
integer errors = 0, checks = 0;
reg [7:0] hs;

task iwm_put(input [7:0] b);
	integer g;
begin
	g = 0;
	hs = 0;
	while (!hs[7] && g < 4000) begin swim_rd(4'd12, hs); g = g + 1; end
	if (g >= 4000) begin errors = errors + 1; $display("FAIL: IWM never ready"); end
	swim_wr(4'd13, b);
end
endtask

// A small hook run between the ROM-like byte pushes (side-flip stressor)
integer flip_at = -1;

// write one data field for (cyl at the head, side at the head, sector n) and
// update the golden model for block blk_of(track, side, n) UNLESS the write is
// expected to be refused (protect) -- the caller says so via expect_land
task guest_write(input integer n, input integer salt, input expect_land,
                 input integer land_trk, input land_side);
	integer q, b, bk, g;
begin
	seed = seed + 1;
	for (q = 0; q < 512; q = q + 1) pay[q] = ({$random(seed)} ^ (salt * 7 + q));
	build_field(n);
	swim_wr(4'd15, 8'h00);               // q7 = 1: write mode
	for (q = 0; q < encn; q = q + 1) begin
		if (q == flip_at) park_head(~cur_side);
		iwm_put(encb[q]);
	end
	// let the last byte reach the decoder, then leave write mode
	g = 0; hs = 0;
	while (!hs[7] && g < 4000) begin swim_rd(4'd12, hs); g = g + 1; end
	repeat (700) @(posedge clk);
	swim_wr(4'd14, 8'h00);               // q7 = 0
	if (expect_land) begin
		bk = blk_of(land_trk, land_side, n);
		for (q = 0; q < 512; q = q + 1) gold[bk * 512 + q] = pay[q];
	end
	// let the committer / writer settle before the next field
	repeat (3000) @(posedge clk);
end
endtask

// ------------------------------------------------------------- helpers
task wait_idle(input integer maxclk);
	integer g;
begin
	g = 0;
	while ((ldr_loading || wr_busy || hps_busy || ldr_wr_req || wc_req) && g < maxclk) begin
		@(posedge clk); g = g + 1;
	end
	repeat (400) @(posedge clk);
	if (g >= maxclk) begin errors = errors + 1; $display("FAIL: timeout waiting idle"); end
end
endtask

task mount_it;
begin
	@(negedge clk); img_size = FBYTES; img_mounted = 1;
	@(negedge clk); img_mounted = 0;
end
endtask

// compare SDRAM and file with the golden bytes; report per-block culprits
task check_all(input [127:0] tag, input check_file);
	integer w, blk, badS, badF, firstS, firstF, nbS, nbF, lastblk;
	reg [15:0] ws, wf;
begin
	badS = 0; badF = 0; firstS = -1; firstF = -1; nbS = 0; nbF = 0;
	lastblk = -1;
	for (w = 0; w < FWORDS; w = w + 1) begin
		ws = {gold[2*w], gold[2*w+1]};
		wf = {gold[2*w+1], gold[2*w]};
		if (ram.mem[24'h600000 + w] !== ws) begin
			badS = badS + 1;
			blk = w / 256;
			if (blk != lastblk) begin
				nbS = nbS + 1;
				if (nbS <= 6) $display("      SDRAM block %0d differs", blk);
				lastblk = blk;
			end
		end
		if (check_file && fm[w] !== wf) badF = badF + 1;
	end
	checks = checks + 1;
	if (badS != 0 || badF != 0) begin
		errors = errors + 1;
		$display("FAIL [%0s]: SDRAM %0d words / %0d blocks wrong, file %0d words wrong", tag, badS, nbS, badF);
	end else $display("ok   [%0s]: SDRAM%0s == golden (%0d words)", tag, check_file ? " and file" : "", FWORDS);
end
endtask

// ------------------------------------------------------------------ main
reg [255:0] tbl = "";
integer wt;

initial begin
	// nibble -> disk byte (the inverse of the decoder's table)
	gt[0]=8'h96; gt[1]=8'h97; gt[2]=8'h9a; gt[3]=8'h9b; gt[4]=8'h9d; gt[5]=8'h9e;
	gt[6]=8'h9f; gt[7]=8'ha6; gt[8]=8'ha7; gt[9]=8'hab; gt[10]=8'hac; gt[11]=8'had;
	gt[12]=8'hae; gt[13]=8'haf; gt[14]=8'hb2; gt[15]=8'hb3; gt[16]=8'hb4; gt[17]=8'hb5;
	gt[18]=8'hb6; gt[19]=8'hb7; gt[20]=8'hb9; gt[21]=8'hba; gt[22]=8'hbb; gt[23]=8'hbc;
	gt[24]=8'hbd; gt[25]=8'hbe; gt[26]=8'hbf; gt[27]=8'hcb; gt[28]=8'hcd; gt[29]=8'hce;
	gt[30]=8'hcf; gt[31]=8'hd3; gt[32]=8'hd6; gt[33]=8'hd7; gt[34]=8'hd9; gt[35]=8'hda;
	gt[36]=8'hdb; gt[37]=8'hdc; gt[38]=8'hdd; gt[39]=8'hde; gt[40]=8'hdf; gt[41]=8'he5;
	gt[42]=8'he6; gt[43]=8'he7; gt[44]=8'he9; gt[45]=8'hea; gt[46]=8'heb; gt[47]=8'hec;
	gt[48]=8'hed; gt[49]=8'hee; gt[50]=8'hef; gt[51]=8'hf2; gt[52]=8'hf3; gt[53]=8'hf4;
	gt[54]=8'hf5; gt[55]=8'hf6; gt[56]=8'hf7; gt[57]=8'hf9; gt[58]=8'hfa; gt[59]=8'hfb;
	gt[60]=8'hfc; gt[61]=8'hfd; gt[62]=8'hfe; gt[63]=8'hff;

	// the file: self-addressing blocks (block no in bytes 0/1, then a ramp), with
	// a valid HFS MDB in block 2 (sig 4244, drNmAlBlks 1594, drAlBlkSiz 512) so
	// the loader's sidedness sniff reports double-sided like a real 800K disk
	for (i = 0; i < FBYTES; i = i + 1) begin : mk
		integer b;
		b = i >> 9;
		gold[i] = ((i & 511) == 0) ? (b & 255) : ((i & 511) == 1) ? ((b >> 8) & 255)
		        : ((b * 3 + (i & 511)) & 255);
	end
	gold[2*512 + 0] = 8'h42; gold[2*512 + 1] = 8'h44;
	gold[2*512 + 18] = 8'h06; gold[2*512 + 19] = 8'h3A;     // 1594
	gold[2*512 + 20] = 8'h00; gold[2*512 + 21] = 8'h00;
	gold[2*512 + 22] = 8'h02; gold[2*512 + 23] = 8'h00;     // 512
	for (i = 0; i < FWORDS; i = i + 1) fm[i] = {gold[2*i+1], gold[2*i]};
	for (i = 0; i < 24'h100000; i = i + 1) ram.mem[24'h600000 + i] = 16'hDEAD;

	if ($value$plusargs("ms=%d", wt)) ms_en = (wt != 0);
	if (!$value$plusargs("acclen=%d", acclen))   acclen = 40;
	if (!$value$plusargs("pollgap=%d", pollgap)) pollgap = 40;

	_reset = 0;
	repeat (40) @(posedge clk);
	_reset = 1; pll_locked = 1;
	repeat (40) @(posedge clk);
	mount_it; wait_idle(40000000);
	repeat (2000) @(posedge clk);
	if (!flp_ins) begin errors = errors + 1; $display("FAIL: drive not inserted after mount"); end
	$display("loader: media_ds=%0d size=%0d ds800=%0d", ldr_mds, ldr_size, ds800);

	// IWM setup like the ROM: internal drive, enabled, q7=0 q6=0
	swim_wr(4'd10, 8'h00);
	swim_wr(4'd9,  8'h00);
	swim_wr(4'd14, 8'h00);
	swim_wr(4'd12, 8'h00);
	repeat (200000) @(posedge clk);       // post-enable squelch
	park_head(0);

	check_all("pre-write image", 1);

	$display("=== W1: every speed zone, both sides, seeks both directions ===");
	// track list jumps inward then outward then inward again
	begin : w1
		integer tl [0:11];
		integer k, t, s, n;
		tl[0]=0;  tl[1]=15; tl[2]=16; tl[3]=31; tl[4]=32; tl[5]=47;
		tl[6]=48; tl[7]=63; tl[8]=64; tl[9]=79; tl[10]=40; tl[11]=5;
		for (k = 0; k < 12; k = k + 1) begin
			t = tl[k];
			for (s = 0; s < 2; s = s + 1) begin
				seek(t, s[0], 0);
				n = (t * 5 + s * 3 + k) % spt_of(t);
				guest_write(n, t * 16 + s, 1, t, s[0]);
				// also the last sector of the track
				n = spt_of(t) - 1;
				guest_write(n, t * 16 + s + 100, 1, t, s[0]);
			end
		end
	end
	wait_idle(40000000);
	check_all("W1", 1);

	$display("=== W2: write right after a seek, side flips between writes ===");
	seek(20, 0, 0); guest_write(3, 201, 1, 20, 0);
	seek(21, 1, 0); guest_write(4, 202, 1, 21, 1);
	seek(21, 0, 0); guest_write(4, 203, 1, 21, 0);
	seek(21, 1, 0); guest_write(0, 204, 1, 21, 1);
	seek(20, 1, 0); guest_write(9, 205, 1, 20, 1);
	seek(60, 0, 0); guest_write(8, 206, 0, 60, 0);   // sector 8 of a 9-spt track: valid
	wait_idle(40000000);
	// (the last write above is legal: spt(60)=9, so sector 8 exists)
	begin : w2fix
		integer q;
		for (q = 0; q < 512; q = q + 1) gold[blk_of(60,0,8) * 512 + q] = pay[q];
	end
	check_all("W2", 1);

	$display("=== W3: write-protect toggled between writes ===");
	seek(10, 0, 0);
	wr_osd = 0;                                  // protected: must not land
	repeat (100) @(posedge clk);
	guest_write(2, 301, 0, 10, 0);
	wr_osd = 1;
	repeat (100) @(posedge clk);
	guest_write(5, 302, 1, 10, 0);
	wr_osd = 0;
	repeat (100) @(posedge clk);
	guest_write(6, 303, 0, 10, 0);
	wr_osd = 1;
	repeat (100) @(posedge clk);
	guest_write(7, 304, 1, 10, 0);
	wait_idle(40000000);
	check_all("W3", 1);

	$display("=== W4: head select flips while a data field is in flight ===");
	// The physical outcome is ambiguous; the data-loss question is only whether
	// OTHER sectors change. The write lands on whichever side the decoder latched
	// at the sector byte; the bench accepts either, but nothing else may change.
	seek(25, 0, 0);
	begin : w4
		integer q, bk0, bk1, bad0, bad1;
		reg [7:0] save0 [0:511];
		reg [7:0] save1 [0:511];
		bk0 = blk_of(25, 0, 6); bk1 = blk_of(25, 1, 6);
		for (q = 0; q < 512; q = q + 1) begin save0[q] = gold[bk0*512+q]; save1[q] = gold[bk1*512+q]; end
		flip_at = 40;
		guest_write(6, 401, 0, 25, 0);
		flip_at = -1;
		wait_idle(40000000);
		bad0 = 0; bad1 = 0;
		for (q = 0; q < 512; q = q + 1) begin
			if (ram.mem[24'h600000 + bk0*256 + q/2][(q&1)?7:15 -: 8] !== pay[q]) bad0 = bad0 + 1;
			if (ram.mem[24'h600000 + bk1*256 + q/2][(q&1)?7:15 -: 8] !== pay[q]) bad1 = bad1 + 1;
		end
		$display("     info: field landed on side0=%0s side1=%0s", bad0 == 0 ? "yes" : "no", bad1 == 0 ? "yes" : "no");
		if (bad0 == 0) for (q = 0; q < 512; q = q + 1) gold[bk0*512+q] = pay[q];
		else if (bad1 == 0) for (q = 0; q < 512; q = q + 1) gold[bk1*512+q] = pay[q];
		else begin
			// landed nowhere: restore, nothing else may differ
		end
	end
	park_head(0);
	check_all("W4", 1);

	$display("=== W5: remount of the same file after writes, then write again ===");
	wait_idle(40000000);
	for (i = 0; i < FWORDS; i = i + 1) if (fm[i] !== {gold[2*i+1], gold[2*i]}) begin
		errors = errors + 1; $display("FAIL: file != golden before remount (word %0d)", i); i = FWORDS;
	end
	mount_it; wait_idle(40000000);
	repeat (2000) @(posedge clk);
	check_all("W5 after remount", 1);
	seek(33, 1, 0); guest_write(1, 501, 1, 33, 1);
	seek(2, 0, 0);  guest_write(11, 502, 1, 2, 0);
	wait_idle(40000000);
	check_all("W5 writes after remount", 1);

	$display("=== W6: remount immediately after a write (writer queue aborted) ===");
	seek(12, 1, 0); guest_write(3, 601, 1, 12, 1);
	mount_it; wait_idle(40000000);
	repeat (2000) @(posedge clk);
	// Whether the sector reached the file depends on the writer having
	// drained; either outcome is legal, but SDRAM must equal the file.
	begin : w6
		integer w, bad;
		bad = 0;
		for (w = 0; w < FWORDS; w = w + 1)
			if (ram.mem[24'h600000 + w] !== {fm[w][7:0], fm[w][15:8]}) bad = bad + 1;
		checks = checks + 1;
		if (bad) begin errors = errors + 1; $display("FAIL [W6]: SDRAM != file after remount (%0d words)", bad); end
		else $display("ok   [W6]: SDRAM == file after remount-with-writes-queued");
	end

	$display("");
	$display("checks=%0d errors=%0d  (file block writes=%0d)", checks, errors, file_wr_blocks);
	if (errors == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
	$finish;
end

initial begin
	#8_000_000_000;
	$display("FAIL: global timeout");
	$display("RESULT: FAIL");
	$finish;
end

endmodule
