// ready commits one backend access; completed advances the CPU exactly once.
module card_paced_cpu_bus #(
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
    output wire [15:0] address,
    output wire [16:0] ram_address,
    output wire write,
    output wire [7:0] write_data,
    output wire sync,
    output wire vector_pull,
    output wire halted,
    output wire high_ram_read,
    output wire high_ram_write
);
    reg response_pending;
    reg [7:0] response_data;
    wire cpu_valid, due;
    wire accepted = valid && ready;
    assign valid = cpu_valid && !response_pending;
    assign completed = cpu_valid && due && (response_pending || accepted);

    card_cycle_pacer #(.CLOCK_HZ(CLOCK_HZ), .NORMAL_HZ(NORMAL_HZ), .FAST_HZ(FAST_HZ)) pace (
        .clk(clk), .reset(reset), .fast(fast), .complete(completed), .due(due)
    );
    card_cpu_bus processor (
        .clk(clk), .reset(reset), .ready(completed),
        .read_data(response_pending ? response_data : read_data),
        .irq_n(irq_n), .nmi_n(nmi_n), .valid(cpu_valid), .address(address),
        .ram_address(ram_address), .write(write), .write_data(write_data),
        .sync(sync), .vector_pull(vector_pull), .halted(halted),
        .high_ram_read(high_ram_read), .high_ram_write(high_ram_write)
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
