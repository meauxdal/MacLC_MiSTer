// Backend ready commits once; timed completed advances the CPU once.
module card_wait_cpu_bus #(
    parameter integer CLOCK_HZ = 65000000,
    parameter integer NORMAL_HZ = 1020000,
    parameter integer FAST_HZ = 1900000
) (
    input wire clk,
    input wire reset,
    input wire fast,
    input wire ready,
    input wire [7:0] read_data,
    input wire irq_n,
    input wire nmi_n,
    output wire valid,
    output wire completed,
    output wire sample_tick,
    output wire [15:0] address,
    output wire [16:0] ram_address,
    output wire write,
    output wire [7:0] write_data,
    output wire sync,
    output wire vector_pull,
    output wire waiting,
    output wire stopped,
    output wire high_ram_read,
    output wire high_ram_write
);
    reg response_pending;
    reg [7:0] response_data;
    wire accepted = valid && ready;
    wire response_ready = response_pending || accepted;
    assign valid = !reset && !waiting && !stopped && !response_pending;
    assign completed = !reset && !waiting && !stopped && sample_tick && response_ready;

    // Free-running CE samples pins through memory waits and WAI.
    card_cycle_pacer #(.CLOCK_HZ(CLOCK_HZ), .NORMAL_HZ(NORMAL_HZ), .FAST_HZ(FAST_HZ)) pace (
        .clk(clk), .reset(reset), .fast(fast), .complete(sample_tick), .due(sample_tick)
    );
    wdc65c02 cpu (
        .clk(clk), .ce(sample_tick), .ce_n(1'b0), .reset(reset), .stall(1'b0),
        .rdy(waiting || response_ready), .stp_nop(1'b0),
        .irq_n(irq_n), .nmi_n(nmi_n), .addr(address), .dout(write_data),
        .din(response_pending ? response_data : read_data), .we(write), .sync(sync),
        .vector_pull(vector_pull), .int_seq(), .rti_done(),
        .in_wai(waiting), .in_stp(stopped),
        .ss_addr(10'b0), .ss_wdata(64'b0), .ss_wren(1'b0), .ss_rdata()
    );
    iie_banking banks (
        .clk(clk), .reset(reset), .complete(completed), .address(address), .write(write),
        .ram_address(ram_address), .high_ram_read(high_ram_read), .high_ram_write(high_ram_write)
    );

    always @(posedge clk) begin
        if (reset) begin
            response_pending <= 0;
            response_data <= 0;
        end else if (completed) response_pending <= 0;
        else if (accepted) begin
            response_pending <= 1;
            response_data <= read_data;
        end
    end
endmodule
