# MacLC project timing constraints (read after sys/sys_top.sdc).
#
# ----------------------------------------------------------------------------
# TG68 kernel — two-period credit (restored 2026-09-15 after the loop fix);
# the HARD CAP era and its reasoning are kept below as history.
# ----------------------------------------------------------------------------
# History. From 2026-06-07 (29e1f69) to 2026-09-12 this block was
#   set_multicycle_path -setup -end 2 -from kernel -to kernel  (+ -hold -end 1)
# on the argument that the kernel (TG68KdotC_Kernel) only advances on
# tg68_clkena pulses that are always >= 2 clk_sys apart, so kernel reg->reg
# paths genuinely have two periods (61.5 ns) to settle. That argument is TRUE
# (re-verified 2026-09-12: every kernel and ALU register is clkena_lw/clkena_in
# gated, the inferred register-file M10Ks have clock enables on both ports, and
# the seed-7 fit runs fine with a worst kernel single-cycle slack of -7.2 ns).
#
# It is nevertheless UNSAFE as the fitter's objective, and it was the cause of
# the "STA met, hardware corrupt, differs per SEED" class that has dogged this
# core since June (July SCSI colour-icon noise -> the always-on anchor hack,
# August F-line bombs, the seed-8 corrupted-fetch fit, the 08-27 QuarkXPress
# Line-1111 hang, and 2026-09-12: same RTL, seed 7 clean, seed 5 hangs at the
# desktop, seed 4 freezes at the desktop, all reproducible). Why: the TG68
# decoder contains a 150-node STRUCTURAL combinational loop (Quartus Critical
# Warning 332081 "Estimating the delays through the loop", TG68KdotC_Kernel.vhd
# ~line 1656: setexecOPC is a function of setstate/next_micro_state, and the
# setstate mux trees use setexecOPC as a select — not a functional oscillator,
# the setexecOPC-guarded branches only set ALU operand-routing flags — but STA
# can only ESTIMATE delay through those mux trees). Given a 61.5 ns budget the
# fitter treats the whole kernel as non-critical and leaves its paths anywhere
# from 32 to 38 ns as STA sees them, with the loop-hidden remainder unbounded and
# re-rolled by every placement; on some seeds the real delay of one decode path
# for one instruction pattern exceeds the two periods that actually exist, and
# that instruction then fails deterministically (Quark typing, Finder start-up).
#
# Experiment E1 (2026-09-12): the seed-4 fit that froze at the desktop, rebuilt
# with ONLY this credit removed, closed the kernel at a single period to
# -0.165 ns (the fitter CAN compact the kernel to ~31 ns when it must) and is
# stable on hardware through boots, QuarkXPress typing and restarts.
#
# So: cap kernel-internal paths at ~one period. The fitter must keep the kernel
# compact (exactly the E1 fit), STA reports honestly against that cap, and the
# genuine two-period budget leaves ~29 ns of real margin for whatever the loop
# estimate under-reports. 32.0 ns = one 30.76 ns period + ~1.2 ns so a normal
# fit reports "met" (E1 worst 30.93 ns); a fit that cannot make 32 ns is a fit
# to reject, not to explain away. set_max_delay overrides any multicycle for
# these paths; hold stays the default single-cycle check. Do NOT restore the
# two-period credit "because the kernel really is two-cycle" — that is exactly
# how the loop's hidden delay gets a free hand. The clean long-term fix is to
# break the structural loop in the kernel so STA is exact; until then this cap
# is the guard. Scope is kernel-INTERNAL only, as before: the tg68k wrapper FSM
# and every CPU<->SDRAM/peripheral path are ordinary single-cycle paths.
#
# ★ 2026-09-15 — THE LOOP IS GONE (branch tg68-break-comb-loop). The mechanism
# described above was wrong: the only real edge was setexecOPC -> datatype (the
# MULU/MULS execute-phase "long" override, the sole setexecOPC-guarded datatype
# write in the decode process) -> the EA-build test
# `opcode(5 downto 3)="010" AND datatype="10"` (42ae7a6, the cmp.l (An) fix,
# 2026-06-02 — so the loop was three months old and not TG68K's) -> setstate /
# next_micro_state -> setexecOPC. Moving that one override to set_datatype
# (identical value at every consumer; see the comment at the MUL site in
# TG68KdotC_Kernel.vhd) removes the edge and adds none. Evidence, same SEED 4
# that failed this cap at -1.024 ns with the loop: no 332081/332125 anywhere,
# kernel-internal worst path 24.8 ns data delay (+6.86 ns against the cap), and
# the warning-count diff against that parent fit is exactly the loop's 135
# messages plus its "timing not met". Functional gates: verilator/tb_mul_modes.v
# (old vs new kernel bus logs identical, every addressing mode) and the boot
# CPU-trace diff. STA is now EXACT for the kernel, so the "loop-hidden
# remainder" argument above no longer applies. THE CAP STAYS for now as a
# policy choice (docs/tg68_comb_loop_plan.md, Phase A). Whether to give the
# genuine two-period budget back is Phase B: decided on hardware across seeds
# 4/5/7, never on STA alone (seed-8 precedent).
#
# ★ PHASE B PASSED 3/3 ON HARDWARE (2026-09-15 late evening, docs/
# tg68_comb_loop_plan.md §7): seeds 4, 5 and 7 with this credit, each booted
# twice, QuarkXPress typing, restart — all clean. Kernel-internal worst paths
# 30.5 / 29.7 / 32.1 ns against 61.5 ns (+28 to +29.5 ns); seed 7 would have
# FAILED the 32 ns cap by 0.1 ns, i.e. the 2.4 ns placement spread that was
# pass-or-fail under the cap is noise under the real budget. The September
# paragraphs above ("Do NOT restore the two-period credit") are kept as
# history: they were right WHILE the loop existed and are superseded by its
# removal. If the "STA met, hardware corrupt" class ever returns, the first
# question is whether a NEW loop or untimed path has appeared (grep 332125),
# not whether this credit is wrong.
#
# (Originally written as:) PHASE B UNDER TEST (2026-09-15, plan §4). With the
# loop gone and STA exact, the two-period credit is restored: every kernel and
# ALU register is clkena-gated and the kernel only advances on tg68_clkena
# pulses >= 2 clk_sys apart (re-verified 2026-09-12), so kernel-internal
# reg->reg paths genuinely have two periods. The hypothesis being tested is the
# September one: that the credit was unsafe ONLY because the loop hid delay
# from STA. Verdict comes from HARDWARE on seeds 4/5/7 (the 2026-09-12 trio:
# one clean, two desktop hangs from one RTL), never from STA. Any failure ->
# put the set_max_delay cap back (line kept below) and record the seed.
# Hold stays the default single-cycle check (-hold -end 1), as in June.
set_multicycle_path -setup -end 2 -from [get_keepers {*TG68KdotC_Kernel*}] -to [get_keepers {*TG68KdotC_Kernel*}]
set_multicycle_path -hold  -end 1 -from [get_keepers {*TG68KdotC_Kernel*}] -to [get_keepers {*TG68KdotC_Kernel*}]
# Phase A cap, retained for a one-line revert if Phase B fails on hardware:
# set_max_delay -from [get_keepers {*TG68KdotC_Kernel*}] -to [get_keepers {*TG68KdotC_Kernel*}] 32.0

# ----------------------------------------------------------------------------
# Peripheral (VPA) read-data register — SCSI read-path fit-stabilization.
# ----------------------------------------------------------------------------
# periph_din_reg (MacLC.sv) captures the peripheral read mux (dataControllerDataOut)
# one clk_sys stage before the CPU samples it on VPA/6800 cycles. Its deepest input
# cone is the SCSI CSR's scsi_bsy bit (scsi.v phase -> |target_bsy -> CSR -> far route
# -> 7-way mux) — historically THE fit-sensitive net that made the SCSI HD read fail
# on some builds (bit6/scsi_bsy read wrong, bit1/scsi_sel read right).
#
# Peripheral reads are E-paced: the kernel stalls at S_WAIT for the E-paced
# (phi2 && xVma) exit (near E-fall) and latches read data two ticks later at
# S_TAIL2, ALWAYS >= 5 clk_sys after the address/select settle (the VMA/E
# handshake takes at least one E quantum; rtl/tg68k/tg68k.v). So the cone into
# periph_din_reg genuinely has multiple clk_sys to resolve, not one. Credit a CONSERVATIVE 2x (61.6 ns @
# 32.5 MHz) — well inside the >=5-cycle window — so STA reports the real margin
# instead of over-constraining this E-paced read to a single 30.8 ns period (the
# "STA passes but HW fails" trap). periph_din_reg is only CONSUMED during VPA reads,
# when its input is held stable by the CPU; its fan-OUT (-> tg68_din_r, near the CPU)
# stays a normal single-cycle path and is deliberately NOT relaxed here.
set_multicycle_path -setup -end 2 -to [get_keepers {*periph_din_reg*}]
set_multicycle_path -hold  -end 1 -to [get_keepers {*periph_din_reg*}]

# ----------------------------------------------------------------------------
# Phase C: clk_sys -> SDRAM demand sequencer — NO multicycle. Deliberate.
# ----------------------------------------------------------------------------
# An earlier attempt (b48b60c, reverted here) credited these paths 2 destination
# periods on the theory that the t[0] start gate made the request data "a full
# clk_sys old" at capture. STA on the post-fit netlist DISPROVED it:
#   slack -6.710 ns, WINDOW 15.381 ns, tg68k|addr[16] -> sdram|sd_addr[12]
# i.e. the capture window is ONE clk_64 period, and the V8 address-translation
# cone needs ~22 ns. The constraint was hiding a 6.7 ns violation; the SDRAM was
# being handed a half-settled row/column address, which corrupted memory and
# bombed the guest (F-line, 2026-08-17). See docs/CPU_Perf_Log.md.
#
# The fix is structural instead: MacLC.sv registers the whole SDRAM request
# bundle (addr/din/ds/oe/we/flp_win/flp_guard) in clk_sys before it reaches the
# sequencer, so the deep cone terminates at a clk_sys flop with a full 30.76 ns
# period, and the sequencer captures from an adjacent register over a short
# route. Both legs are then honest single-cycle paths that STA checks for real.
# DO NOT re-add a multicycle here — if these paths fail, fix the pipelining.

# ----------------------------------------------------------------------------
# Pixel-clock domain (pll_video) CDC — false-path the 2FF synchronizer heads.
# ----------------------------------------------------------------------------
# The V8 scanout runs on clk_vid (pll_video, reconfigured 25.175/15.664/58.742
# MHz). sys_top.sdc decouples every clock domain with set_clock_groups, but
# its core-PLL pattern (*|pll|pll_inst|...) matches only the MAIN pll — the
# pll_video clock landed in NO group, so every framework path touching
# CLK_VIDEO (ascal video-in, OSD, HDMI transfer) was timed against unrelated
# domains: design-wide false violations (worst -27.9 ns, clk_sys TNS -89k).
# Declare it asynchronous to everything else, exactly like pll_hdmi/pll_audio.
#
# The deliberate clk_sys<->clk_vid crossings this blesses are all safe by
# construction: (a) dual-clock M10Ks (vram_bram framebuffer, ariel palette —
# no timed cross-port arc), (b) 2FF *_meta synchronizers (config into the
# video module, video-domain reset, VBL/HBL back into clk_sys), and (c) the
# quasi-static words_per_line bus into addrController's VRAM write packing —
# incoherent only across a monitor/depth change, when the guest redraws the
# whole screen anyway.
set native_video_clocks [get_clocks {emu|pllv|*|divclk}]
if {[get_collection_size [get_registers -nowarn {*crt_tv|*|capture_fifo|*}]] == 0} {
    set_clock_groups -asynchronous -group $native_video_clocks
} else {
    # A clock-group false path would override the FIFO Gray max-delay/skew
    # budgets below. Preserve the normal native-domain exceptions while
    # leaving the two deliberate Gray buses available for physical timing.
    # Quartus 17 all_registers has no -clock option. Follow the native PLL
    # through clock selectors as well as buffers/inverters. -no_logic alone
    # stops at the HDMI clock selector, missing its downstream registers.
    # Restrict the additional traversal to register clock pins so a clock
    # used as data cannot cause unrelated data endpoints to be cut.
    # Keep the no-logic fanout too, for native-clock output-port exceptions.
    set native_keepers [get_keepers -nowarn {__tv_empty_collection__}]
    set native_clock_pins [get_pins -compatibility_mode {*|clk}]
    foreach_in_collection native_clock $native_video_clocks {
        set native_keepers [add_to_collection $native_keepers \
            [get_fanouts -no_logic [get_clock_info -targets $native_clock]]]
        set native_keepers [add_to_collection $native_keepers \
            [get_fanouts -through $native_clock_pins [get_clock_info -targets $native_clock]]]
    }
    set native_gray [get_registers {*crt_tv|*|capture_fifo|wr_gray[*]}]
    set native_gray_receiver [get_registers {*crt_tv|*|capture_fifo|rd_gray_meta[*]}]
    # Fail closed if hierarchy/clock propagation changes: both native FIFO
    # endpoints must belong to the clock fanout used for these exceptions.
    foreach native_endpoint [list $native_gray $native_gray_receiver] {
        if {[get_collection_size $native_endpoint] == 0 ||
            [get_collection_size $native_keepers] -
            [get_collection_size [remove_from_collection $native_keepers $native_endpoint]] !=
            [get_collection_size $native_endpoint]} {
            error "Native FIFO endpoints missing from video-clock fanout"
        }
    }
    set other_clocks [remove_from_collection [get_clocks *] $native_video_clocks]
    set_false_path -from [remove_from_collection $native_keepers $native_gray] -to $other_clocks
    set_false_path -from $other_clocks -to [remove_from_collection $native_keepers $native_gray_receiver]

    # TimeQuest propagates BOTH native and HDMI clocks through the selectors.
    # Restore the native/HDMI clock-pair cuts from the normal profile too:
    # keeper exceptions alone cannot distinguish the two clock relationships.
    # Without these, the fitter adds ~9 ns of hold delay to the HDMI output
    # pipeline to satisfy impossible cross-PLL transfers, breaking the real
    # 148.5 MHz same-clock paths. These cuts do not include clk_100m, so the
    # capture FIFO Gray max-delay/skew constraints remain effective.
    set native_hdmi_clocks [get_clocks {pll_hdmi|pll_hdmi_inst|*|divclk}]
    if {[get_collection_size $native_hdmi_clocks] != 0} {
        set_false_path -from $native_video_clocks -to $native_hdmi_clocks
        set_false_path -from $native_hdmi_clocks -to $native_video_clocks
    }
}

# Belt-and-braces documentation of the synchronizer heads (redundant with the
# clock group above, harmless).
set_false_path -to [get_keepers {*vmode_meta* *monid_meta*}]
# Test-pattern controls can be constants and disappear during synthesis.
set native_test_meta [get_keepers -nowarn {*tbyp_meta* *tsel_meta*}]
if {[get_collection_size $native_test_meta] != 0} {
    set_false_path -to $native_test_meta
}
set_false_path -to [get_keepers {*vidrst_meta* *vbl_meta* *hbl_meta*}]

# ----------------------------------------------------------------------------
# SDRAM interface I/O constraints (2026-09-12).
# ----------------------------------------------------------------------------
# Until now the SDRAM pins carried NO I/O constraints at all: report_ucp on the
# shipped builds listed all 16 SDRAM_DQ[*] inputs and the whole A/BA/DQ/DQM/cmd
# output set as unconstrained, so STA never checked the read data eye. The eye
# was therefore set by the fitter's routing alone — which is why a pure reseed
# (SEED 8 -> 4) shipped a core that hangs QuarkXPress with a Line-1111 F-line
# exception while the same RTL at another seed is clean. Full measurement and
# bisect: docs/plan_sdram_read_capture_2026-09-12.md.
#
# SDRAM_CLK is altddio_out(datain_h=0, datain_l=1) of clk_64, i.e. the INVERTED
# clk_64 — declare it as such so the chip's launch edges are modelled correctly.
#
# Delay values: Alliance AS4C32M16SB-7 (64/128 MB MiSTer modules; Winbond
# W9825G6KH-6 on the 32 MB module is equivalent):
#   tAC(CL2) 6.0 ns, tOH 2.5 ns, tIS(tDS) 1.5 ns, tIH(tDH) 0.8 ns,
#   plus ~0.5 ns of board trace allowance on the max numbers.
#
# The read capture is rtl/sdram.v's sd_data_q — a single I/O-cell register on
# the FALLING edge of clk_64. The chip launches on ITS rising edge (= a clk_64
# falling edge) and we capture on the NEXT clk_64 falling edge, which is the
# default single-cycle relationship: no multicycle is needed or wanted here.
# Measured eye at that register (three seeds, 0.04 ns spread): +2.2 ns setup,
# +6.5 ns hold — the edge sits early in an ~8.8 ns eye; the fat side is hold.
# From there the word is re-timed by sd_data_r (fabric, next falling edge:
# a full period for the I/O-cell -> core route) and consumed on the posedge
# after that; the floppy copy `dout` loads on that same falling edge. All of
# those are ordinary same-clock paths (negedge->negedge full period,
# negedge->posedge half period) that STA checks natively — nothing to add.
# ** If the pin capture is ever moved back to a posedge register, this must be
# re-derived — the pre-2026-09-12 STATE_READ capture needed
# `set_multicycle_path -setup -end 2` to be reported honestly at all. And a
# posedge stage directly behind sd_data_q does NOT close: that hand-off has
# half a period minus ~1.2 ns of I/O-cell clock skew against a ~6 ns route,
# and failed by -0.14..-0.64 ns on three seeds (2026-09-12). **
#
# sdram_clk is deliberately NOT added to the -exclusive clock groups in
# sys/sys_top.sdc: a clock that appears in no group stays related to every
# other clock, which is exactly what makes these paths get timed against
# clk_64 instead of being cut.
create_generated_clock -name sdram_clk -invert \
  -source [get_pins {emu|pll|pll_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk}] \
  [get_ports {SDRAM_CLK}]

# chip -> FPGA (read data)
set_input_delay  -clock sdram_clk -max 6.5 [get_ports {SDRAM_DQ[*]}]
set_input_delay  -clock sdram_clk -min 2.5 [get_ports {SDRAM_DQ[*]}]

# FPGA -> chip (address, command, write data, byte masks)
set SDRAM_OUT [get_ports {SDRAM_A[*] SDRAM_BA[*] SDRAM_DQ[*] SDRAM_DQMH SDRAM_DQML SDRAM_nCAS SDRAM_nRAS SDRAM_nWE SDRAM_nCS}]
set_output_delay -clock sdram_clk -max  2.0 $SDRAM_OUT
set_output_delay -clock sdram_clk -min -0.8 $SDRAM_OUT

# Independent TV domain: constrain actual crossings individually. A blanket
# asynchronous clock-group cut would also hide the held configuration bus.
set tv525_clocks [get_clocks -nowarn {*tv525_pll|*|divclk}]
if {[get_collection_size [get_registers -nowarn {*crt_tv|*}]] != 0} {
    if {[get_collection_size $tv525_clocks] == 0} {
        error "TV diagnostic exists but its derived 27 MHz PLL clock was not found"
    }
    set_false_path -to [get_registers {*crt_tv|*|req_meta *crt_tv|*|ack_meta *crt_tv|disable_meta}]
    # PLL-lock assertion is asynchronous; release is a 3FF chain per domain.
    # The RTL locked alias is not a fitted PLL pin name. Target only the
    # asynchronous clear pins; keep the release chain's D paths timed.
    set tv525_reset_clear [get_pins -compatibility_mode {*crt_tv|tv_reset_pipe*|clrn *crt_tv|sys_reset_pipe*|clrn}]
    if {[get_collection_size $tv525_reset_clear] == 0} {
        error "TV PLL reset-chain asynchronous clear pins were not found"
    }
    set_false_path -to $tv525_reset_clear
    # Dedicated pin-enable register also clears asynchronously on PLL loss.
    # Optional for timing analysis of fits made before the output-stage repair.
    set tv525_pin_clear [get_pins -nowarn -compatibility_mode {*crt_tv|pin_ready*|clrn}]
    if {[get_collection_size $tv525_pin_clear] != 0} {
        set_false_path -to $tv525_pin_clear
    }
    # Receiver has two synchronizer stages plus a frame-boundary wait before
    # sampling the held bus. Bound physical data delay to one 27 MHz period.
    set tv525_payload [get_registers {*crt_tv|*|config_payload*}]
    set tv525_config [get_registers {*crt_tv|*|tv_config*}]
    if {[get_collection_size $tv525_payload] == 0 || [get_collection_size $tv525_config] == 0} {
        error "TV OSD mailbox endpoints were not found; review synthesis hierarchy"
    }
    set_max_delay 30.0 -from $tv525_payload -to $tv525_config
    set_false_path -hold -from $tv525_payload -to $tv525_config
    # Native capture FIFO: bound Gray-pointer skew/delay to less than the
    # fastest source period. RAM ports have no combinational cross-clock arc.
    set tv_fifo [get_registers -nowarn {*crt_tv|*|capture_fifo|*}]
    if {[get_collection_size $tv_fifo] != 0} {
        set tv_wr_gray [get_registers {*crt_tv|*|capture_fifo|wr_gray[*]}]
        set tv_rd_gray [get_registers {*crt_tv|*|capture_fifo|rd_gray[*]}]
        set tv_wr_meta [get_registers {*crt_tv|*|capture_fifo|wr_gray_meta[*]}]
        set tv_rd_meta [get_registers {*crt_tv|*|capture_fifo|rd_gray_meta[*]}]
        foreach tv_gray_endpoint [list $tv_wr_gray $tv_rd_gray $tv_wr_meta $tv_rd_meta] {
            if {[get_collection_size $tv_gray_endpoint] == 0} {
                error "TV capture FIFO Gray endpoints missing; review synthesis hierarchy"
            }
        }
        set_max_delay 8.0 -from $tv_wr_gray -to $tv_wr_meta
        set_max_delay 8.0 -from $tv_rd_gray -to $tv_rd_meta
        set_max_skew 8.0 -from $tv_wr_gray -to $tv_wr_meta
        set_max_skew 8.0 -from $tv_rd_gray -to $tv_rd_meta
        # Quartus 17 also removes skew paths when they have a hold false path.
        # These are asynchronous FIRST synchronizer stages: there is no
        # source/destination phase or hold contract. Use a deliberately loose
        # minimum instead, preserving the real 8 ns delay AND skew budgets.
        # 100 ns exceeds both domains' periods; this is not a fitted-slack
        # adjustment. Meta->sync paths retain ordinary setup/hold checks.
        set_min_delay -100.0 -from $tv_wr_gray -to $tv_wr_meta
        set_min_delay -100.0 -from $tv_rd_gray -to $tv_rd_meta
        # Pair/line toggle mailboxes; line_payload remains held until the
        # full line completes. The receiver reads it only after two FFs.
        set_false_path -to [get_registers {*crt_tv|*|pair_meta *crt_tv|*|line_meta *crt_tv|*|pair_ack_meta *crt_tv|*|line_ack_meta *crt_tv|*|display_meta tv_mem_reset_meta}]
        set tv_line_payload [get_registers {*crt_tv|*|line_payload[*]}]
        set tv_line_bank [get_registers {*crt_tv|*|store|bank}]
        set tv_line_address [get_registers {*crt_tv|*|store|address[*]}]
        set tv_line_words [get_registers {*crt_tv|*|store|read_words[*]}]
        foreach tv_line_endpoint [list $tv_line_payload $tv_line_bank $tv_line_address $tv_line_words] {
            if {[get_collection_size $tv_line_endpoint] == 0} {
                error "TV held-line mailbox endpoint missing; review synthesis hierarchy"
            }
        }
        set tv_line_receivers [add_to_collection [add_to_collection $tv_line_bank $tv_line_address] $tv_line_words]
        set_max_delay 20.0 -from $tv_line_payload -to $tv_line_receivers
        set_false_path -hold -from $tv_line_payload -to $tv_line_receivers
    }
    # Analog DAC has no receiver clock. Quartus 17 includes launch-clock
    # latency in this 10 ns clock-to-pin budget (not just register-Q routing).
    # Retain that stricter contract; do not offset latency using fit results.
    # SD_SPI_CS carries the board's sync-on-Y drive and needs the same budget.
    set tv525_dac_ports [get_ports {VGA_R* VGA_G* VGA_B* VGA_HS VGA_VS SDIO_CLK SDIO_CMD SDIO_DAT* SD_SPI_CS}]
    set_max_delay 10.0 -from $tv525_clocks -to $tv525_dac_ports
    set_false_path -hold -from $tv525_clocks -to $tv525_dac_ports
}
