`timescale 1ns/1ps
module tb_iie_video_switch;
    reg clk = 0, reset = 1, phase = 0;
    always #5 clk = !clk;
    always @(posedge clk) phase <= !phase;
    wire [31:0] address;
    wire [15:0] data_out, data_in;
    wire rw_n, as_n, uds_n, lds_n;
    wire [7:0] pvia_data, video_config, ram_config;
    wire io_access = address[23:8] == 16'hF260 && !as_n && (!uds_n || !lds_n);
    reg [15:0] memory [0:131071];
    reg setup = 1, pvia_reset = 1;
    reg [7:0] initial_mode;
    integer mode, checkpoints = 0;
    string image;
    assign data_in = io_access ? {pvia_data, pvia_data} : memory[address[17:1]];
    tg68k host (
        .clk(clk), .reset(reset), .phi1(phase), .phi2(!phase), .cpu(2'b11),
        .dtack_n(1'b0), .rw_n(rw_n), .as_n(as_n), .uds_n(uds_n), .lds_n(lds_n),
        .fc(), .reset_n(), .E(), .E_div(1'b1), .E_PosClkEn(), .E_NegClkEn(),
        .vma_n(), .vpa_n(1'b1), .br_n(1'b1), .bg_n(), .bgack_n(1'b1), .ipl(3'b111),
        .berr(1'b0), .din(data_in), .dout(data_out), .longword(), .addr(address),
        .addr_early(), .busstate()
    );
    pseudovia pvia (
        .clk_sys(clk), .reset(pvia_reset), .soft_rst(1'b0),
        .addr(setup ? 13'h10 : address[12:0]),
        .data_in(setup ? initial_mode : data_out[7:0]), .data_out(pvia_data),
        .we(setup || !rw_n), .req(setup || io_access),
        .vblank_irq(1'b0), .slot_irq(1'b0), .asc_irq(1'b0),
        .scsi_irq(1'b0), .scsi_drq(1'b0), .irq_out(),
        .ram_config(8'hC0), .monitor_id(4'h2), .video_config(video_config),
        .ram_config_out(ram_config), .ram_configured()
    );
    reg active = 0;
    always @(posedge clk) begin
        if (as_n) active <= 0;
        if (!reset && !as_n && !rw_n && (!uds_n || !lds_n)) begin
            if (!io_access) begin
                if (!uds_n) memory[address[17:1]][15:8] <= data_out[15:8];
                if (!lds_n) memory[address[17:1]][7:0] <= data_out[7:0];
            end
            if (address[31:1] == (32'h300 >> 1) && !active) begin
                active <= 1;
                if (video_config[2:0] !== (checkpoints < 2 ? 3'(mode + 1) : 3'(mode)))
                    $fatal(1, "switch %0d: format=%0d initial=%0d", checkpoints, video_config[2:0], mode);
                if (ram_config !== (checkpoints < 2 ? 8'hC5 : 8'hC4))
                    $fatal(1, "switch bit or RAM size changed: %h", ram_config);
                checkpoints <= checkpoints + 1;
                if (checkpoints == 3) begin
                    $display("PASS original CODE1 entry, repeated entry, exit, repeated exit; initial format %0d", mode);
                    $finish;
                end
            end
        end
    end
    initial begin
        if (!$value$plusargs("image=%s", image) || !$value$plusargs("mode=%d", mode))
            $fatal(1, "missing image or mode");
        initial_mode = 8'(mode);
        $readmemh(image, memory);
        repeat (4) @(negedge clk);
        // Program the initial format while the host remains reset.
        pvia_reset = 0;
        repeat (2) @(negedge clk);
        setup = 0;
        reset = 0;
    end
    initial begin
        #2000000;
        $fatal(1, "video switch timeout address=%h checkpoints=%0d", address, checkpoints);
    end
endmodule
