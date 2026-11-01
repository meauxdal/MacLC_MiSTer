`timescale 1ns/1ps
module tb_seams;
    reg iie_card_claim_raw = 0, _cpuAS = 1;
    reg [2:0] cpuFC = 1;
    reg [31:0] cpuAddr = 0;
    reg iie_card_dtack_n = 1, iie_card_error = 0;
    reg [15:0] iie_card_read_data = 16'h1357;
    reg iie_rom_oe_raw = 0, iie_ram_oe_raw = 0, iie_ram_we_raw = 0;
    wire _romOE, _ramOE, _ramWE, _cpuVPA, _cpuDTACK;
    reg fc7_iack = 0, fc7_berr = 0, slot_space = 0;
    reg selectVRAM = 0, selectSCSIDMA = 0, selectRAM = 1, selectROM = 1;
    reg icache_hit = 1, scsiDREQ = 1, sdram_cpu_done = 1, _cpuRW = 1, dtack_en = 1;
    reg sdma_berr = 0, vpa_periph_read = 1;
    reg [15:0] icache_data = 16'h2222, periph_din_reg = 16'h3333, dataControllerDataOut = 16'h4444;
    // EXTRACTED
    initial begin
        #1;
        _cpuAS = 0; cpuAddr = 32'h80000000; iie_card_claim_raw = 1;
        #1;
        if (!_romOE || !_ramOE || !_ramWE) $fatal(1, "claimed overlay strobes escaped");
        if (!_cpuDTACK || !_cpuVPA || cpu_din_muxed != 16'h1357 || cacheable || snoopable)
            $fatal(1, "card wait lost bus priority");
        iie_card_dtack_n = 0;
        #1;
        if (_cpuDTACK) $fatal(1, "card completion lost");
        iie_card_error = 1;
        #1;
        if (!_cpuDTACK || cpu_berr) $fatal(1, "unsupported card access did not hold without BERR");
        cpuFC = 7; fc7_iack = 1; fc7_berr = 1;
        #1;
        if (iie_card_claim || _cpuVPA || !_cpuDTACK || !cpu_berr)
            $fatal(1, "FC7 priority changed");
        cpuFC = 1; fc7_iack = 0; fc7_berr = 0; _cpuAS = 1;
        #1;
        if (iie_card_claim || _romOE || _ramOE || _ramWE) $fatal(1, "idle claim or strobe masking");
        iie_card_claim_raw = 0; _cpuAS = 0; slot_space = 1;
        #1;
        if (_cpuDTACK || !_cpuVPA || cpu_din_muxed != 16'hffff || !cacheable || !snoopable)
            $fatal(1, "noncard slot response changed");
        slot_space = 0;
        #1;
        if (_cpuDTACK || cpu_din_muxed != icache_data) $fatal(1, "noncard cache response changed");
        $display("PASS extracted MacLC seams: overlay, cache, DTACK, VPA, FC7, idle, slot and error hold");
        $finish;
    end
endmodule
