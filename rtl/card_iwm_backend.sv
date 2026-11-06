// IIe card external 5.25 drive behind card_iwm_frontend.
// One drive on enable 1; drive 2 reads as absent. WOZ bitstream tracks only.
// The read/write sequencer follows the Apple-II_MiSTer disk_ii_woz P6 model
// (IWM mode 0, Disk II compatible). The drive and WOZ engines are vendored in
// rtl/woz. They run from a fractional 14.318 MHz enable; the controller runs at
// clk so the hps_io buffer is served at full rate.
//
// control: [3:0] phases, [4] motor, [5] drive select, [6] q6, [7] q7,
//          [12:8] mode, [20:13] write data, [21] data write, [22] reset
// drive:   [7:0] data, [8] sense, [9] write busy, [10] underrun, [11] enabled
module card_iwm_backend #(
    parameter integer CLK_HZ = 32500000,
    parameter integer TRACK_ADDR_WIDTH = 13,
    parameter integer HOLD_TICKS = 14318182
) (
    input wire clk,
    input wire cold_reset,
    input wire [22:0] control,
    output wire [11:0] drive,
    input wire write_protect,
    output wire active,

    output wire [31:0] sd_lba,
    output wire sd_rd,
    output wire sd_wr,
    input wire sd_ack,
    input wire [7:0] sd_buff_addr,
    input wire [15:0] sd_buff_dout,
    output reg [15:0] sd_buff_din,
    input wire sd_buff_wr,
    input wire img_mounted,
    input wire img_readonly,
    input wire [63:0] img_size
);
    localparam integer CE_HZ = 14318182;
    localparam [23:0] SPINUP_TICKS = 24'd1000;

    wire [3:0] phases = control[3:0];
    wire motor = control[4];
    wire drive2 = control[5];
    wire q6 = control[6];
    wire q7 = control[7];
    wire [4:0] mode = control[12:8];
    wire [7:0] cpu_data = control[20:13];
    wire cpu_load = control[21];
    wire seq_reset = control[22];

    // 14.318 MHz enable, exact on average.
    reg ce = 0;
    reg [31:0] ce_acc = 0;
    always @(posedge clk) begin
        if (ce_acc + CE_HZ >= CLK_HZ) begin
            ce <= 1;
            ce_acc <= ce_acc + CE_HZ - CLK_HZ;
        end else begin
            ce <= 0;
            ce_acc <= ce_acc + CE_HZ;
        end
    end

    // A data-register write is one clk wide; hold it for the next enable.
    reg load_pending = 0;
    reg [7:0] load_byte = 0;
    always @(posedge clk) begin
        if (seq_reset) load_pending <= 0;
        else if (cpu_load) begin
            load_pending <= 1;
            load_byte <= cpu_data;
        end else if (ce) load_pending <= 0;
    end

    // Enable holdover: one second after motor off unless mode bit 2 is set.
    reg [23:0] hold = 0;
    always @(posedge clk) begin
        if (seq_reset || (!motor && mode[2])) hold <= 0;
        else if (motor) hold <= HOLD_TICKS[23:0];
        else if (ce && hold != 0) hold <= hold - 1'd1;
    end
    wire enabled = motor || hold != 0;

    // Spin-up glitch filter ahead of the drive model.
    reg spinning = 0;
    reg [9:0] spinup = 0;
    always @(posedge clk) begin
        if (cold_reset || !enabled) begin
            spinning <= 0;
            spinup <= 0;
        end else if (ce && !spinning) begin
            if (spinup == SPINUP_TICKS[9:0]) spinning <= 1;
            else spinup <= spinup + 1'd1;
        end
    end

    // Mount pulse; a cold reset clears the controller, so re-pulse after it.
    reg mounted_d = 0, reset_d = 0, mount = 0, remount = 0, media = 0;
    always @(posedge clk) begin
        mounted_d <= img_mounted;
        reset_d <= cold_reset;
        if (!mounted_d && img_mounted) media <= img_size != 0;
        if (cold_reset) begin
            mount <= 0;
            remount <= 0;
        end else if (reset_d) remount <= media;
        else if (!mounted_d && img_mounted) begin
            if (mount) begin
                mount <= 0;
                remount <= img_size != 0;
            end else mount <= img_size != 0;
        end else if (remount) begin
            mount <= 1;
            remount <= 0;
        end
    end

    // hps_io is 16 bits wide, low byte first; the controller takes bytes.
    reg [1:0] wr_phase = 0;
    reg [7:0] wr_addr = 0;
    reg [15:0] wr_word = 0;
    reg [2:0] rd_step = 3'd4;
    reg [7:0] rd_addr = 0;
    reg [7:0] rd_lo = 0;
    wire [7:0] ctrl_din;
    always @(posedge clk) begin
        if (sd_buff_wr) begin
            wr_phase <= 2'd1;
            wr_addr <= sd_buff_addr;
            wr_word <= sd_buff_dout;
        end else if (wr_phase != 0) wr_phase <= wr_phase == 2'd1 ? 2'd2 : 2'd0;
        // Fetch even then odd byte; the controller's output lags its address by two clocks.
        if (rd_step != 3'd4) rd_step <= rd_step + 1'd1;
        else if (rd_addr != sd_buff_addr) begin
            rd_addr <= sd_buff_addr;
            rd_step <= 0;
        end
        if (rd_step == 3'd2) rd_lo <= ctrl_din;
        if (rd_step == 3'd3) sd_buff_din <= {ctrl_din, rd_lo};
    end
    wire [8:0] ctrl_addr = wr_phase != 0 ? {wr_addr, wr_phase == 2'd2} :
                           {rd_step == 3'd4 ? sd_buff_addr : rd_addr, rd_step == 3'd1};
    wire [7:0] ctrl_dout = wr_phase == 2'd2 ? wr_word[15:8] : wr_word[7:0];
    wire ctrl_wr = wr_phase != 0;

    wire flux, wp, mounted, load_done, is_flux, ctrl_wp;
    wire [8:0] qtrack;
    wire [5:0] bit_timer;
    wire [15:0] bram_addr, write_addr;
    wire [7:0] write_byte, bit_data, timing;
    wire write_we;
    wire [31:0] bit_count, flux_size, flux_ticks;
    reg write_bit = 0, write_strobe = 0;

    // The drive saw a registered track RAM at 14 MHz; present it one enable late.
    reg [7:0] bit_data_ce = 0;
    always @(posedge clk) if (ce) bit_data_ce <= bit_data;

    // Controller pulses last one clk; hold them until the drive samples.
    reg load_pending_ce = 0;
    always @(posedge clk) begin
        if (ce) load_pending_ce <= 0;
        else if (load_done) load_pending_ce <= 1;
    end

    // The head model rests two quarter-tracks above the TMAP index.
    wire [7:0] track_id = qtrack >= 9'd2 ? qtrack[7:0] - 8'd2 : 8'd0;
    wire here = !drive2;
    wire motor_here = spinning && mounted && here;

    flux_drive drive_model (
        .IS_35_INCH(1'b0), .DRIVE_ID(2'd0), .CLK_14M(clk), .CE_14M(ce), .RESET(cold_reset),
        .PHASES(here ? phases : 4'b0), .IMMEDIATE_PHASES(here ? phases : 4'b0),
        .LATCHED_SENSE_REG(3'b0), .IWM_MODE(5'b0), .MOTOR_ON(motor_here),
        .SW_MOTOR_ON(motor && here), .DISKREG_SEL(1'b0), .SEL35(1'b0),
        .DRIVE_SELECT(drive2), .DRIVE_SLOT(1'b0), .DISK_MOUNTED(mounted),
        .DISK_WP(ctrl_wp || write_protect || !mounted), .DOUBLE_SIDED(1'b0),
        .FLUX_TRANSITION(flux), .STEP_EVENT(), .TRACK0_EVENT(), .WRITE_PROTECT(wp),
        .SENSE(), .DISK_SWITCHED_OUT(), .STEP_BUSY_OUT(), .STEP_DIR_OUT(),
        .MOTOR_ON_SENSE_OUT(), .AT_TRACK0_OUT(), .MOTOR_SPINNING(), .DRIVE_READY(),
        .TRACK(), .HEAD_QTRACK(qtrack), .EJECT_REQ(), .BIT_POSITION(),
        .BIT_TIMER_OUT(bit_timer), .TRACK_BIT_COUNT(bit_count), .TRACK_LOADED(mounted),
        .TRACK_LOAD_COMPLETE(load_done || load_pending_ce), .BRAM_ADDR(bram_addr),
        .BRAM_DATA(bit_data_ce), .OPTIMAL_BIT_TIMING(timing), .IS_FLUX_TRACK(is_flux),
        .FLUX_DATA_SIZE(flux_size), .FLUX_TOTAL_TICKS(flux_ticks),
        .WRITE_BIT(write_bit), .WRITE_STROBE(write_strobe && here), .WRITE_MODE(q7 && here),
        .WRITE_BYTE_OUT(write_byte), .WRITE_WE_OUT(write_we), .WRITE_ADDR_OUT(write_addr),
        .SD_TRACK_REQ(), .SD_TRACK_STROBE(), .SD_TRACK_ACK(1'b0), .CHUNK_RELOAD_REQ(),
        .CHUNK_NEEDED(), .CHUNK_LOADED(2'b00), .CHUNK_LOADING(1'b0)
    );

    woz_floppy_controller #(.IS_35_INCH(0), .BRAM_ADDR_WIDTH(TRACK_ADDR_WIDTH)) controller (
        .clk(clk), .reset(cold_reset),
        .sd_lba(sd_lba), .sd_rd(sd_rd), .sd_wr(sd_wr), .sd_ack(sd_ack),
        .sd_buff_addr(ctrl_addr), .sd_buff_dout(ctrl_dout), .sd_buff_din(ctrl_din),
        .sd_buff_wr(ctrl_wr), .img_mounted(mount), .img_readonly(img_readonly),
        .img_size(img_size), .track_id(track_id), .ready(), .disk_mounted(mounted),
        .busy(), .active(spinning && here), .bit_count(bit_count), .bit_addr(bram_addr),
        .stable_side(1'b0), .bit_data(bit_data), .bit_data_in(write_byte),
        .bit_we(write_we), .bit_wr_addr(write_addr), .track_load_complete(load_done),
        .is_flux_track(is_flux), .flux_data_size(flux_size), .flux_total_ticks(flux_ticks),
        .track_data_valid(), .disk_type_mismatch(), .disk_write_protected(ctrl_wp),
        .optimal_bit_timing(timing), .dbg_load_sum(), .dbg_load_bytes(), .dbg_load_blocks()
    );

    // Write cells use a local timer from the same cell lookup as the drive.
    wire [5:0] cell_base;
    wire [9:0] cell_step;
    woz_cell525 cell_lut (
        .clk(clk), .timing(timing), .bit_count(bit_count), .cell_base(cell_base),
        .cell_step(cell_step), .half_base(), .half_step()
    );

    // Logic state sequencer, advanced once per enable.
    reg [7:0] sr = 0, sr_stall = 0;
    reg armed = 0, flux_seen = 0, prev_flux = 0;
    reg [3:0] stall = 0;
    reg [5:0] cell_timer = 6'd56;
    reg [9:0] cell_frac = 0;
    wire [9:0] frac_next = cell_frac + cell_step;
    wire flux_here = flux && here;
    wire flux_edge = flux_here && !prev_flux;
    // Read cells end on the drive's own timer so the window cannot drift.
    wire drive_cell_end = bit_timer == 6'd1;
    always @(posedge clk) if (ce) begin
        prev_flux <= flux_here;
        write_strobe <= 0;
        if (stall != 0) stall <= stall - 1'd1;
        if (seq_reset) begin
            sr <= 0;
            armed <= 0;
            stall <= 0;
            flux_seen <= 0;
            cell_timer <= 6'd56;
            cell_frac <= 0;
            write_bit <= 0;
        end else begin
            if (flux_edge) flux_seen <= 1;
            if (load_pending) begin
                // Bit 7 reaches the disk half a cell after the store.
                sr <= load_byte;
                cell_timer <= {1'b0, cell_base[5:1]};
                cell_frac <= 0;
                armed <= 0;
            end else if (q6 && !q7) begin
                sr <= {8{wp}};
                armed <= 0;
                if (drive_cell_end) flux_seen <= 0;
            end else if (q7 ? cell_timer == 6'd1 : drive_cell_end) begin
                flux_seen <= 0;
                if (q7) begin
                    if (frac_next >= 10'd1000) begin
                        cell_timer <= cell_base + 6'd1;
                        cell_frac <= frac_next - 10'd1000;
                    end else begin
                        cell_timer <= cell_base;
                        cell_frac <= frac_next;
                    end
                    write_bit <= sr[7];
                    write_strobe <= 1;
                    sr <= {sr[6:0], 1'b0};
                    armed <= 0;
                end else if (sr[7]) begin
                    // Hold until a pulse, then restart with it as the leading one.
                    if (!armed) armed <= flux_seen || flux_edge;
                    else begin
                        armed <= 0;
                        sr <= {6'b0, 1'b1, flux_seen || flux_edge};
                        sr_stall <= sr;
                        stall <= 4'd8;
                    end
                end else begin
                    sr <= {sr[6:0], flux_seen || flux_edge};
                    armed <= 0;
                end
            end else if (q7) cell_timer <= cell_timer - 1'd1;
        end
    end

    // TODO: latch, asynchronous handshake, fast and 8 MHz mode bits.
    assign drive = {enabled, 1'b0, 1'b0, here ? wp : 1'b1, stall != 0 ? sr_stall : sr};
    assign active = enabled && here;
endmodule
