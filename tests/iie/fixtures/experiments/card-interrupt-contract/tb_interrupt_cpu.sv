`timescale 1ns/1ps
module tb_interrupt_cpu;
    reg clk = 0;
    always #5 clk = !clk;
    reg reset = 1;
    reg irq_n = 1;
    integer inject = 0, delay_scale = 0, ticks = 0, started_at = 0;
    reg started = 0, nmi_done = 0, permitted = 0, pending_report = 0;
    reg cli_seen = 0, operand_seen = 0, loop_seen = 0;
    integer reports = 0, report_age = 0, nmi_vectors = 0, irq_vectors = 0, reset_vectors = 0, rtis = 0;
    reg [15:0] nmi_return, irq_return;
    reg [7:0] nmi_flags, irq_flags, irq_report;
    wire valid, write, sync, vector_pull, halted, high_read, high_write;
    wire [15:0] address;
    wire [16:0] ram_address;
    wire [7:0] write_data;
    wire [7:0] read_data;
    reg [7:0] memory [0:131071];
    reg [1023:0] image_path;
    wire opcode02 = valid && sync && address == 16'h202F;
    // Candidate board behavior, separate from the unchanged WDC opcode decoder.
    wire nmi_n = !(inject != 0 && !nmi_done && (started || opcode02));
    wire report_store = started && write && address == 16'hC07D;
    wire ready = valid && !reset && (!report_store || permitted) &&
                 (delay_scale == 0 || ticks % 4 != 0);
    card_cpu_bus processor (
        .clk(clk), .reset(reset), .ready(ready), .read_data(read_data),
        .irq_n(irq_n), .nmi_n(nmi_n), .valid(valid), .address(address),
        .ram_address(ram_address), .write(write), .write_data(write_data),
        .sync(sync), .vector_pull(vector_pull), .halted(halted),
        .high_ram_read(high_read), .high_ram_write(high_write)
    );
    assign read_data = address == 16'hC07D || address == 16'hC0E8 ||
                       address == 16'hC0E9 || address == 16'hC0A0 ? 8'hA5 :
                       address == 16'hC000 ? 8'hA0 :
                       address == 16'hC010 ? 8'h80 :
                       address == 16'hC019 ? 8'h00 : memory[ram_address];
    always @(posedge clk) begin
        ticks <= ticks + 1;
        if (opcode02 && !started) begin
            started <= 1;
            started_at <= ticks;
        end
        if (!reset && valid && !write && !sync && address == 16'h2030 && ready) operand_seen <= 1;
        if (!reset && valid && sync && address == 16'h2031 && ready) cli_seen <= 1;
        if (!reset && valid && sync && address == 16'h2032 && ready) loop_seen <= 1;
        if (ready) begin
            if (write && address < 16'hC000) memory[ram_address] <= write_data;
            if (vector_pull && address == 16'hFFFC) reset_vectors <= reset_vectors + 1;
            if (vector_pull && address == 16'hFFFA) begin
                nmi_vectors <= nmi_vectors + 1;
                nmi_done <= 1;
            end
            if (vector_pull && address == 16'hFFFE) irq_vectors <= irq_vectors + 1;
            if (processor.cpu.rti_done) rtis <= rtis + 1;
            if (report_store) permitted <= 0;
        end
        if (report_store && !permitted && !pending_report) begin
            reports <= reports + 1;
            pending_report <= 1;
            report_age <= 0;
            if (inject == 0) $fatal(1, "bare opcode02 unexpectedly produced a report");
            if (reports == 0 && write_data != 2) $fatal(1, "NMI handler did not produce2");
            if (reports == 0) begin
                nmi_return <= {memory[16'h01FD], memory[16'h01FC]};
                nmi_flags <= memory[16'h01FB];
            end
            if (reports == 1) begin
                irq_return <= {memory[16'h01FD], memory[16'h01FC]};
                irq_flags <= memory[16'h01FB];
                irq_report <= write_data;
            end
            if (reports == 2) begin
                if (write_data != 1 || memory[16'h200A] != 1 || processor.cpu.reg_s != 8'hFD ||
                    nmi_vectors != 1 || irq_vectors != 1 || reset_vectors != 1 || rtis != 2 ||
                    !operand_seen || !cli_seen || !loop_seen || nmi_return != 16'h2031 ||
                    nmi_flags[4] || !nmi_flags[2] || irq_flags[4] || irq_flags[2])
                    $fatal(1, "candidate NMI/IRQ sequence mismatch");
                $display("PASS CPU candidate: NMI return=%h report2, IRQ return=%h report=%h, main report1, two RTIs; delay=%0d", nmi_return, irq_return, irq_report, delay_scale);
                $finish;
            end
        end
        if (pending_report) begin
            report_age <= report_age + 1;
            if (report_age == 5) begin
                pending_report <= 0;
                permitted <= 1;
                // Candidate host command bit5 asserts/deasserts the IRQ pin.
                if (reports == 1) irq_n <= 0;
                if (reports == 2) irq_n <= 1;
            end
        end
        if (started && inject == 0 && ticks - started_at > 500) begin
            if (reports != 0 || nmi_vectors != 0 || irq_vectors != 0 || reset_vectors != 1 ||
                memory[16'h200A] != 0 || !operand_seen || !cli_seen || !loop_seen || rtis != 0)
                $fatal(1, "bare opcode02 baseline mismatch");
            $display("PASS CPU baseline: opcode02 consumes operand, no interrupts/reports, original counter loop; delay=%0d", delay_scale);
            $finish;
        end
        if (ticks > 10000 || halted) $fatal(1, "CPU interrupt test timeout/halt");
    end
    initial begin
        if (!$value$plusargs("image=%s", image_path)) $fatal(1, "missing logical image");
        if ($value$plusargs("inject=%d", inject)) begin end
        if ($value$plusargs("delay=%d", delay_scale)) begin end
        $readmemh(image_path, memory);
        repeat (3) @(negedge clk);
        reset = 0;
    end
endmodule
