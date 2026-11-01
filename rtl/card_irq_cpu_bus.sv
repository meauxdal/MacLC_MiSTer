// Experimental CPU bus. Memory writes complete only when ready is asserted.
module card_irq_cpu_bus (
    input wire clk,
    input wire reset,
    input wire sample_tick,
    input wire ready,
    input wire [7:0] read_data,
    input wire irq_n,
    input wire nmi_n,
    output wire valid,
    output wire [15:0] address,
    output wire [16:0] ram_address,
    output wire write,
    output wire [7:0] write_data,
    output wire sync,
    output wire vector_pull,
    output wire rti_done,
    output wire halted,
    output wire high_ram_read,
    output wire high_ram_write
);
    wire waiting, stopped;
    wire complete = valid && ready;
    // WAI samples interrupt pins without issuing a bus request.
    assign halted = stopped;
    assign valid = !reset && !waiting && !stopped;

    wdc65c02 cpu (
        .clk(clk), .ce(sample_tick), .ce_n(1'b0), .reset(reset),
        .stall(1'b0), .rdy(waiting || ready), .stp_nop(1'b0),
        .irq_n(irq_n), .nmi_n(nmi_n), .addr(address),
        .dout(write_data), .din(read_data), .we(write), .sync(sync),
        .vector_pull(vector_pull), .int_seq(), .rti_done(rti_done),
        .in_wai(waiting), .in_stp(stopped),
        .ss_addr(10'b0), .ss_wdata(64'b0), .ss_wren(1'b0), .ss_rdata()
    );

    iie_banking banks (
        .clk(clk), .reset(reset), .complete(complete),
        .address(address), .write(write), .ram_address(ram_address),
        .high_ram_read(high_ram_read), .high_ram_write(high_ram_write)
    );
endmodule

// Ordinary IIe RAM selection; card firmware and host contexts are separate.
module iie_banking (
    input wire clk,
    input wire reset,
    input wire complete,
    input wire [15:0] address,
    input wire write,
    output wire [16:0] ram_address,
    output wire high_ram_read,
    output wire high_ram_write
);
    reg ramrd, ramwrt, altzp, store80, page2, hires;
    reg lc_read, lc_write, lc_prewrite, lc_bank1;
    reg aux;
    wire selected = write ? ramwrt : ramrd;
    wire high_ram = address >= 16'hD000;
    wire [15:0] physical = (address[15:12] == 4'hD && lc_bank1)
        ? {4'hC, address[11:0]} : address;

    always @* begin
        aux = selected;
        if (address < 16'h0200 || address >= 16'hC000)
            aux = altzp;
        else if (store80 && address >= 16'h0400 && address < 16'h0800)
            aux = page2;
        else if (store80 && hires && address >= 16'h2000 && address < 16'h4000)
            aux = page2;
    end
    assign ram_address = {aux, physical};
    assign high_ram_read = high_ram && lc_read;
    assign high_ram_write = high_ram && lc_write;

    always @(posedge clk) begin
        if (reset) begin
            ramrd <= 0;
            ramwrt <= 0;
            altzp <= 0;
            store80 <= 0;
            page2 <= 0;
            hires <= 0;
            lc_read <= 0;
            lc_write <= 1;
            lc_prewrite <= 0;
            lc_bank1 <= 0;
        end else if (complete) begin
            if (write) begin
                case (address)
                    16'hC000, 16'hC001: store80 <= address[0];
                    16'hC002, 16'hC003: ramrd <= address[0];
                    16'hC004, 16'hC005: ramwrt <= address[0];
                    16'hC008, 16'hC009: altzp <= address[0];
                    default: ;
                endcase
            end
            case (address)
                16'hC054, 16'hC055: page2 <= address[0];
                16'hC056, 16'hC057: hires <= address[0];
                default: ;
            endcase
            if (address[15:4] == 12'hC08) begin
                lc_bank1 <= address[3];
                lc_read <= !(address[0] ^ address[1]);
                lc_prewrite <= address[0] && !write;
                if (!address[0]) lc_write <= 0;
                else if (lc_prewrite && !write) lc_write <= 1;
            end
        end
    end
endmodule
