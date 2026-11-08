// ============================================================================
// vram_ddr3.sv -- Mac LC framebuffer in HPS DDR3, with a two-line M10K cache
// for the V8 scanout.  Replaces vram_bram (384 M10K) with about 10 M10K.
//
// WHAT IT MIRRORS: exactly what vram_bram held.  CPU VRAM reads still come
// from SDRAM (addrController); this module only keeps the packed scanout copy
// that the CPU's VRAM writes mirror into (vram_waddr / vram_we, one strobe per
// write cycle), and serves the V8's scanline prefetch from it.
//
// WHY IT FITS NOW (vram_bram.sv explains why the old external-memory video
// paths starved): the V8 no longer reads external memory on its own clock.
// It still prefetches the NEXT scanline into its ping-pong linebuf, one word
// per clock, but from a small cache here that a DMA filled one scanline
// earlier still.  So the DDR3 has a whole line time (>= 14 us) to deliver at
// most 129 beats, and DDR3 latency never reaches the pixels.
//
//   clk_sys  CPU write strobe -> capture register + toggle.  clk_mem is the
//            same PLL at 2x clk_sys (65 / 32.5 MHz, zero phase), so the
//            crossing is an ordinary timed single-cycle path, no synchronizer.
//   clk_mem  write queue (512 deep, M10K) -> write gather (same-beat merge,
//            up to 8 sequential beats per burst) -> DDR3; line DMA (32-beat
//            bursts) into the line cache; every dequeued write is also
//            patched into any cached line it falls in (snoop).
//   clk_vid  line controller: keeps the line the V8 is fetching (fetch base)
//            and the one after it in the two cache slots, asking clk_mem for
//            a fill by toggle handshake.  The V8's reads hit the cache with
//            the same one-clock registered latency vram_bram had.
//
// DDR3 LAYOUT: packed 16-bit word P lives in 64-bit beat DDR_BASE + P[17:2],
// lane P[1:0] (bits 16*lane +: 16).  Up to 512 KB (18-bit packed address;
// 384 KB used) from byte 0x21C00000, right above the 480i frame store
// [0x21800000,0x21c00000).
//
// COHERENCE: one DDR3 master, in order.  Gathered writes are issued (all
// beats accepted) before any later burst read, and nothing is dequeued while
// a read burst is outstanding.  So a fill returns every write dequeued
// before it; a write dequeued after it is patched into the cache by the
// snoop.  A write still queued when a line is fetched shows once it drains:
// the queue latency (microseconds) is the only staleness, the same order as
// vram_bram's one-pixel race.
//
// CACHE SLOTS: 2 slots x 256 beats x 64 bits, as eight byte-wide simple-
// dual-port RAMs (vram_bram's lesson: byte-wide arrays with whole-word write
// enables infer M10K reliably in Quartus 17).  A line spans at most 129
// beats (512 words starting mid-beat); index = {slot, beat offset}.
// ============================================================================
module vram_ddr3 #(
    parameter [28:0] DDR_BASE = 29'h0438_0000,  // byte 0x21C00000 >> 3
    parameter integer WQ_AW  = 9                // write queue depth 2^WQ_AW
)(
    // CPU write mirror (clk_sys), the same strobe vram_bram port A took
    input  wire        clk_sys,
    input  wire [17:0] cpu_addr,
    input  wire [15:0] cpu_din,
    input  wire  [1:0] cpu_be,      // {upper, lower} byte strobes
    input  wire        cpu_we,

    // V8 scanout (clk_vid)
    input  wire        clk_vid,
    input  wire        reset_vid,
    input  wire [17:0] vid_base,    // packed base of the line being fetched
    input  wire [10:0] vid_wpl,     // words per line
    input  wire [17:0] vid_raddr,   // V8 read address (vid_base + index)
    output wire [15:0] vid_rdata,   // registered: valid the clock after

    // DDR3 Avalon master (clk_mem)
    input  wire        clk_mem,
    output reg  [28:0] ddr_address,
    output reg   [7:0] ddr_burstcount,
    output reg  [63:0] ddr_writedata,
    output reg   [7:0] ddr_byteenable,
    output reg         ddr_read,
    output reg         ddr_write,
    input  wire        ddr_waitrequest,
    input  wire        ddr_readdatavalid,
    input  wire [63:0] ddr_readdata,

    // diagnostics (clk_mem)
    output reg         wq_overflow,      // sticky: a CPU write was dropped
    output reg [WQ_AW:0] wq_peak         // write queue high-water mark
);

localparam integer WQ_DEPTH = 1 << WQ_AW;
localparam [7:0]   BURST = 8'd32;        // line DMA burst
localparam integer GB = 8;               // write gather, beats

initial begin
    ddr_address = 29'd0; ddr_burstcount = 8'd1; ddr_writedata = 64'd0;
    ddr_byteenable = 8'd0; ddr_read = 1'b0; ddr_write = 1'b0;
    wq_overflow = 1'b0; wq_peak = '0;
end

// ----------------------------------------------------------------------------
// clk_sys: capture the write.  The strobe is one clk_sys wide and writes are
// several clk_sys apart (68k bus cycles), but a toggle keeps even back-to-
// back strobes distinct.
// ----------------------------------------------------------------------------
reg [35:0] cap = 36'd0;
reg        cap_tog = 1'b0;
always @(posedge clk_sys)
    if (cpu_we) begin
        cap     <= {cpu_be, cpu_din, cpu_addr};
        cap_tog <= ~cap_tog;
    end

// clk_mem samples the clk_sys registers directly (related clocks, timed).
reg [35:0] cap_m = 36'd0;
reg        cap_tog_m = 1'b0, cap_tog_q = 1'b0;
always @(posedge clk_mem) begin
    cap_m     <= cap;
    cap_tog_m <= cap_tog;
    cap_tog_q <= cap_tog_m;
end
wire wq_push = cap_tog_m ^ cap_tog_q;   // cap_m holds the new write now

// ----------------------------------------------------------------------------
// clk_mem: write queue, show-ahead.  The M10K read address runs one entry
// ahead on a pop, so wq_q is always the head entry; an entry is counted a
// clock after it is written, by which time the read has picked it up.
// ----------------------------------------------------------------------------
(* ramstyle = "M10K,no_rw_check" *) reg [35:0] wq_mem [0:WQ_DEPTH-1];
reg [WQ_AW-1:0]  wq_wptr = '0, wq_rptr = '0;
reg [WQ_AW:0]    wq_count = '0;
reg              wq_push_d = 1'b0;
reg [35:0]       wq_q = 36'd0;
wire             wq_full = (wq_count + {{WQ_AW{1'b0}}, wq_push_d}) >= WQ_DEPTH[WQ_AW:0];
wire             wq_ready = (wq_count != '0);
reg              wq_pop;
wire [WQ_AW-1:0] wq_raddr = wq_pop ? wq_rptr + 1'b1 : wq_rptr;

always @(posedge clk_mem) begin
    if (wq_push && !wq_full) wq_mem[wq_wptr] <= cap_m;
    wq_q <= wq_mem[wq_raddr];
end

always @(posedge clk_mem) begin
    wq_push_d <= wq_push && !wq_full;
    if (wq_push && !wq_full) wq_wptr <= wq_wptr + 1'b1;
    if (wq_push && wq_full) wq_overflow <= 1'b1;
    if (wq_pop) wq_rptr <= wq_rptr + 1'b1;
    case ({wq_push_d, wq_pop})
        2'b10: wq_count <= wq_count + 1'b1;
        2'b01: wq_count <= wq_count - 1'b1;
        default: ;
    endcase
    if (wq_count > wq_peak) wq_peak <= wq_count;
end

// ----------------------------------------------------------------------------
// Line cache storage: eight byte lanes, written on clk_mem, read on clk_vid.
// Byte b of a beat = bits 8*b +: 8; 16-bit lane l = bytes 2l (lo), 2l+1 (hi).
// (Spelled out, not a generate loop: Quartus drops a ramstyle on an array
// declared inside one -- see MacLC475's vram_ddr3.)
// ----------------------------------------------------------------------------
reg  [8:0] lc_waddr = 9'd0;
reg  [7:0] lc_we = 8'h00;
reg [63:0] lc_wdata = 64'd0;
wire [8:0] lc_raddr;
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b0 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b1 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b2 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b3 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b4 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b5 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b6 [0:511];
(* ramstyle = "M10K,no_rw_check" *) reg [7:0] lc_b7 [0:511];
reg [7:0] lc_q0, lc_q1, lc_q2, lc_q3, lc_q4, lc_q5, lc_q6, lc_q7;
always @(posedge clk_mem) if (lc_we[0]) lc_b0[lc_waddr] <= lc_wdata[ 7: 0];
always @(posedge clk_mem) if (lc_we[1]) lc_b1[lc_waddr] <= lc_wdata[15: 8];
always @(posedge clk_mem) if (lc_we[2]) lc_b2[lc_waddr] <= lc_wdata[23:16];
always @(posedge clk_mem) if (lc_we[3]) lc_b3[lc_waddr] <= lc_wdata[31:24];
always @(posedge clk_mem) if (lc_we[4]) lc_b4[lc_waddr] <= lc_wdata[39:32];
always @(posedge clk_mem) if (lc_we[5]) lc_b5[lc_waddr] <= lc_wdata[47:40];
always @(posedge clk_mem) if (lc_we[6]) lc_b6[lc_waddr] <= lc_wdata[55:48];
always @(posedge clk_mem) if (lc_we[7]) lc_b7[lc_waddr] <= lc_wdata[63:56];
always @(posedge clk_vid) lc_q0 <= lc_b0[lc_raddr];
always @(posedge clk_vid) lc_q1 <= lc_b1[lc_raddr];
always @(posedge clk_vid) lc_q2 <= lc_b2[lc_raddr];
always @(posedge clk_vid) lc_q3 <= lc_b3[lc_raddr];
always @(posedge clk_vid) lc_q4 <= lc_b4[lc_raddr];
always @(posedge clk_vid) lc_q5 <= lc_b5[lc_raddr];
always @(posedge clk_vid) lc_q6 <= lc_b6[lc_raddr];
always @(posedge clk_vid) lc_q7 <= lc_b7[lc_raddr];
wire [63:0] lc_q = {lc_q7, lc_q6, lc_q5, lc_q4, lc_q3, lc_q2, lc_q1, lc_q0};

// ----------------------------------------------------------------------------
// clk_vid: line controller.  key = {words per line, packed base}: a depth or
// monitor change alters wpl, so it can never hit a line cached for another
// mode.  One fill request outstanding at a time.
// ----------------------------------------------------------------------------
reg  [28:0] tag0 = 29'd0, tag1 = 29'd0;
reg         val0 = 1'b0, val1 = 1'b0;
reg         req_tog = 1'b0;
reg         req_slot = 1'b0;
reg  [17:0] req_base = 18'd0;
reg  [10:0] req_wpl = 11'd0;
reg         done_tog = 1'b0;            // clk_mem
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg         vdm_done_meta = 1'b0;
reg         done_v = 1'b0;
always @(posedge clk_vid) begin
    vdm_done_meta <= done_tog;
    done_v        <= vdm_done_meta;
end
wire        busy_v = req_tog ^ done_v;

wire [17:0] nxt_base = vid_base + {7'd0, vid_wpl};
wire [28:0] key_cur  = {vid_wpl, vid_base};
wire [28:0] key_nxt  = {vid_wpl, nxt_base};
wire cur0 = val0 && (tag0 == key_cur), cur1 = val1 && (tag1 == key_cur);
wire nxt0 = val0 && (tag0 == key_nxt), nxt1 = val1 && (tag1 == key_nxt);

always @(posedge clk_vid) begin
    if (reset_vid) begin
        val0 <= 1'b0;
        val1 <= 1'b0;
    end else if (!busy_v && vid_wpl != 11'd0) begin
        if (!cur0 && !cur1) begin
            // the line being fetched is missing (reset, mode change, or the
            // first line of a frame): fill it, sparing a slot with the next
            req_slot <= nxt0;
            req_base <= vid_base;
            req_wpl  <= vid_wpl;
            req_tog  <= ~req_tog;
            if (nxt0) begin tag1 <= key_cur; val1 <= 1'b1; end
            else      begin tag0 <= key_cur; val0 <= 1'b1; end
        end else if (!nxt0 && !nxt1) begin
            // steady state: prefetch the line after it into the other slot
            req_slot <= cur0;
            req_base <= nxt_base;
            req_wpl  <= vid_wpl;
            req_tog  <= ~req_tog;
            if (cur0) begin tag1 <= key_nxt; val1 <= 1'b1; end
            else      begin tag0 <= key_nxt; val0 <= 1'b1; end
        end
    end
end

// Read: index = vid_raddr - vid_base (< 1024, so ten low bits do), beat
// offset = (index + base lane) / 4.  Registered in the RAM; lane picked from
// the registered address, the same one-clock latency as vram_bram.
wire [9:0] rd_index = vid_raddr[9:0] - vid_base[9:0];
wire [9:0] rd_lanes = rd_index + {8'd0, vid_base[1:0]};
assign lc_raddr = {cur1, rd_lanes[9:2]};
reg [1:0] rd_lane = 2'd0;
always @(posedge clk_vid) rd_lane <= vid_raddr[1:0];
assign vid_rdata = lc_q[16*rd_lane +: 16];

// ----------------------------------------------------------------------------
// clk_mem: fill requests in, done toggle out.  The request fields have been
// stable since before req_tog moved, and stay until done_tog answers.
// ----------------------------------------------------------------------------
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg vdm_req_meta = 1'b0;
reg req_m = 1'b0, req_seen = 1'b0;
always @(posedge clk_mem) begin
    vdm_req_meta <= req_tog;
    req_m        <= vdm_req_meta;
end
wire req_new = (req_m != req_seen);

// request geometry: first beat, beat count (<= 129)
wire [17:0] req_end   = req_base + {7'd0, req_wpl} - 18'd1;
wire [15:0] req_first = req_base[17:2];
wire  [7:0] req_beats = 8'(req_end[17:2] - req_first + 16'd1);

// slot metadata for the snoop
reg [15:0] sbase0 = 16'd0, sbase1 = 16'd0;   // first beat (packed >> 2)
reg  [7:0] slen0 = 8'd0, slen1 = 8'd0;       // beats, 0 = empty

// DMA state
reg        dma_pend = 1'b0;
reg        dma_slot = 1'b0;
reg [15:0] dma_beat = 16'd0;     // next DDR beat to request
reg  [7:0] dma_left = 8'd0;      // beats not yet requested
reg  [7:0] dma_idx = 8'd0;       // next cache index to write
reg  [7:0] dma_rx = 8'd0;        // beats still due for the burst in flight

// Write gather: dequeued writes merge into up to GB sequential beats, sent
// as one burst.  Under DDR3 contention the queue backs up and bursts form by
// themselves; on a quiet bus a lone write goes out at once.
reg [63:0] bb_data [0:GB-1];
reg  [7:0] bb_be   [0:GB-1];
reg [15:0] bb_beat0 = 16'd0;
reg  [3:0] bb_n = 4'd0;          // beats gathered
reg  [2:0] wr_i = 3'd0;          // beat being written

// the head entry
wire [17:0] e_addr  = wq_q[17:0];
wire [15:0] e_data  = wq_q[33:18];
wire  [1:0] e_be2   = wq_q[35:34];
wire [15:0] e_beat  = e_addr[17:2];
wire  [7:0] e_be    = {6'd0, e_be2} << (2 * e_addr[1:0]);
wire [15:0] bb_last = bb_beat0 + {12'd0, bb_n} - 16'd1;
wire        e_merge  = (bb_n != 4'd0) && (e_beat == bb_last);
wire        e_append = (bb_n != 4'd0) && (bb_n != 4'(GB)) && (e_beat == bb_last + 16'd1);
wire        e_fits   = (bb_n == 4'd0) || e_merge || e_append;
wire  [3:0] e_slot4  = e_merge ? bb_n - 4'd1 : bb_n;
wire  [2:0] e_slot   = e_slot4[2:0];

// snoop hits of the head entry; a beat at a line boundary sits in both
// slots, and the second patch takes the next clock (sn1_pend)
wire [15:0] off0 = e_beat - sbase0, off1 = e_beat - sbase1;
wire        hit0 = (off0 < {8'd0, slen0}), hit1 = (off1 < {8'd0, slen1});
reg         sn1_pend = 1'b0;
reg  [7:0]  sn1_off = 8'd0;
reg  [7:0]  sn1_be = 8'd0;
reg [15:0]  sn1_data = 16'd0;

localparam [1:0] M_IDLE = 2'd0, M_WR = 2'd1, M_RD = 2'd2, M_RDATA = 2'd3;
reg [1:0] mst = M_IDLE;
reg       last_dma = 1'b0;

// Pop when the head fits the gather, unless a fill request is to be taken
// (only with nothing gathered) or a DMA burst is owed its turn.
always @(*) begin
    wq_pop = (mst == M_IDLE) && wq_ready && e_fits && !sn1_pend &&
             !(req_new && bb_n == 4'd0) &&
             !(dma_pend && !last_dma && bb_n == 4'd0);
end

integer gi;
always @(posedge clk_mem) begin
    lc_we <= 8'h00;

    case (mst)
    M_IDLE: begin
        if (sn1_pend) begin
            lc_waddr <= {1'b1, sn1_off};
            lc_wdata <= {4{sn1_data}};
            lc_we    <= sn1_be;
            sn1_pend <= 1'b0;
        end else if (req_new && bb_n == 4'd0) begin
            // take a fill request: nothing gathered, so every write the
            // snoop saw under the old slot range is already in the DDR3
            // ahead of the fill
            req_seen <= req_m;
            if (req_beats == 8'd0 || req_wpl == 11'd0) begin
                done_tog <= ~done_tog;
            end else begin
                dma_pend <= 1'b1;
                dma_slot <= req_slot;
                dma_beat <= req_first;
                dma_left <= req_beats;
                dma_idx  <= 8'd0;
                if (req_slot) begin sbase1 <= req_first; slen1 <= req_beats; end
                else          begin sbase0 <= req_first; slen0 <= req_beats; end
            end
        end else if (wq_pop) begin
            if (bb_n == 4'd0) bb_beat0 <= e_beat;
            if (!e_merge) begin
                bb_n          <= bb_n + 4'd1;
                bb_be[e_slot] <= e_be;
            end else begin
                bb_be[e_slot] <= bb_be[e_slot] | e_be;
            end
            for (gi = 0; gi < 4; gi = gi + 1)
                if (e_addr[1:0] == gi[1:0]) begin
                    if (e_be2[0]) bb_data[e_slot][16*gi +: 8]     <= e_data[7:0];
                    if (e_be2[1]) bb_data[e_slot][16*gi + 8 +: 8] <= e_data[15:8];
                end
            last_dma <= 1'b0;
            // snoop: patch the cached lines now (the gathered burst goes to
            // the DDR3 ahead of any later fill, see the fill request above)
            if (hit0) begin
                lc_waddr <= {1'b0, off0[7:0]};
                lc_wdata <= {4{e_data}};
                lc_we    <= e_be;
            end else if (hit1) begin
                lc_waddr <= {1'b1, off1[7:0]};
                lc_wdata <= {4{e_data}};
                lc_we    <= e_be;
            end
            sn1_pend <= hit0 && hit1;
            sn1_off  <= off1[7:0];
            sn1_be   <= e_be;
            sn1_data <= e_data;
        end else if (bb_n != 4'd0) begin
            // the head does not continue the gather (or there is none): send
            ddr_address    <= DDR_BASE + {13'd0, bb_beat0};
            ddr_burstcount <= {4'd0, bb_n};
            ddr_writedata  <= bb_data[0];
            ddr_byteenable <= bb_be[0];
            ddr_write      <= 1'b1;
            wr_i           <= 3'd0;
            mst            <= M_WR;
        end else if (dma_pend) begin
            ddr_address    <= DDR_BASE + {13'd0, dma_beat};
            ddr_burstcount <= (dma_left > BURST) ? BURST : dma_left;
            dma_rx         <= (dma_left > BURST) ? BURST : dma_left;
            ddr_read       <= 1'b1;
            last_dma       <= 1'b1;
            mst            <= M_RD;
        end
    end

    // stream the gathered beats; no burst read may pass them
    M_WR: begin
        if (!ddr_waitrequest) begin
            if ({1'b0, wr_i} == bb_n - 4'd1) begin
                ddr_write <= 1'b0;
                bb_n      <= 4'd0;
                mst       <= M_IDLE;
            end else begin
                wr_i           <= wr_i + 3'd1;
                ddr_writedata  <= bb_data[wr_i + 3'd1];
                ddr_byteenable <= bb_be[wr_i + 3'd1];
            end
        end
    end

    M_RD: begin
        if (!ddr_waitrequest) begin
            ddr_read <= 1'b0;
            mst      <= M_RDATA;
        end
    end
    M_RDATA: begin
        if (ddr_readdatavalid) begin
            lc_waddr <= {dma_slot, dma_idx};
            lc_wdata <= ddr_readdata;
            lc_we    <= 8'hFF;
            dma_idx  <= dma_idx + 1'b1;
            dma_rx   <= dma_rx - 1'b1;
            if (dma_rx == 8'd1) begin
                dma_beat <= dma_beat + {8'd0, ddr_burstcount};
                dma_left <= dma_left - ddr_burstcount;
                if (dma_left == ddr_burstcount) begin
                    dma_pend <= 1'b0;
                    done_tog <= ~done_tog;
                end
                mst <= M_IDLE;
            end
        end
    end
    endcase
end

wire unused_ok = &{1'b0, vid_raddr[17:10], rd_lanes[1:0], req_end[1:0], e_slot4[3]};

endmodule
