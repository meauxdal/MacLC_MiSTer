`timescale 1ns/1ps
module tb_candidate_guards;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0;
    reg req_valid = 0, req_word = 0, req_write = 0, rsp_ready = 0;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error, fault, boundary;
    wire [15:0] rsp_rdata, cpu_address, capture_address;
    wire capture_valid;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    reg mem_ready = 1, mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    reg forced_valid = 0, forced_write = 0, forced_halted = 0;
    reg forced_vector = 0;
    reg [15:0] forced_address = 0;
    integer native_requests = 0, guard_checks = 0, data_checks = 0;
    card_candidate dut (.*);
    always @(posedge clk)
        if (por_n && mem_valid && mem_ready) native_requests <= native_requests + 1;
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task clean_reset;
        begin
            forced_valid = 0;
            forced_halted = 0;
            forced_vector = 0;
            por_n = 0;
            tick; tick;
            por_n = 1;
            tick;
            if (fault || mem_valid || cpu_completed || capture_valid || dut.cpu_memory_wait)
                $fatal(1, "guard reset setup");
        end
    endtask
    task unsupported_access(input [15:0] address, input writing, input vector_access);
        begin
            clean_reset;
            forced_address = address;
            forced_write = writing;
            forced_vector = vector_access;
            forced_valid = 1;
            #1;
            if (!dut.unsupported_cpu || dut.master_valid[1] || dut.cpu_ready || mem_valid)
                $fatal(1, "unsupported access issued before fault: %h write=%b", address, writing);
            tick;
            if (!fault) $fatal(1, "missing unsupported fault: %h write=%b", address, writing);
            repeat (4) begin
                tick;
                if (dut.master_valid[1] || dut.cpu_ready || mem_valid || cpu_completed || capture_valid || dut.cpu_memory_wait)
                    $fatal(1, "unsupported access changed CPU/memory/capture: %h", address);
            end
            guard_checks = guard_checks + 1;
        end
    endtask
    task data_read(input expected_error, input [7:0] expected_data);
        begin
            req_valid = 1;
            req_write = 0;
            req_word = 0;
            req_offset = 6'h0C;
            if (!req_ready) $fatal(1, "data read unexpectedly blocked");
            tick;
            req_valid = 0;
            repeat (4) begin
                if (!rsp_valid || rsp_error !== expected_error || rsp_rdata !== {8'b0, expected_data})
                    $fatal(1, "capture data response error/data mismatch");
                tick;
            end
            rsp_ready = 1;
            tick;
            rsp_ready = 0;
            if (rsp_valid) $fatal(1, "capture data response did not retire");
            data_checks = data_checks + 1;
        end
    endtask
    initial begin
        // Force only the CPU-facing bus for focused guards, not guest bytes.
        force dut.cpu_running = 1'b1;
        force dut.cpu_valid = forced_valid;
        force dut.cpu_address = forced_address;
        force dut.cpu_write = forced_write;
        force dut.cpu_halted = forced_halted;
        force dut.cpu_sync = 1'b0;
        force dut.vector_pull = forced_vector;
        clean_reset;
        // A supported RAM read can issue, so the negative checks are not vacuous.
        forced_address = 16'h0123;
        forced_write = 0;
        forced_valid = 1;
        #1;
        if (!dut.master_valid[1] || dut.unsupported_cpu) $fatal(1, "positive RAM issue gate");
        forced_valid = 0;
        unsupported_access(16'hD000, 0, 0);
        unsupported_access(16'hD000, 1, 0);
        unsupported_access(16'hE000, 0, 0);
        unsupported_access(16'hE000, 1, 0);
        unsupported_access(16'hFFFA, 1, 1);
        unsupported_access(16'hFFFC, 1, 1);
        unsupported_access(16'hFFFE, 1, 1);
        unsupported_access(16'hC004, 0, 0);
        clean_reset;
        forced_address = 16'h2055;
        forced_valid = 0;
        forced_halted = 1;
        #1;
        if (dut.master_valid[1] || dut.cpu_ready) $fatal(1, "halted CPU issued an access");
        tick;
        if (!fault) $fatal(1, "halted CPU valid-low did not fault");
        repeat (4) tick;
        if (mem_valid || cpu_completed || capture_valid || dut.cpu_memory_wait)
            $fatal(1, "halted CPU changed CPU/memory/capture");
        guard_checks = guard_checks + 1;
        clean_reset;
        data_read(1, 0);  // No capture.
        force dut.capture_valid = 1'b1;
        force dut.capture_write = 1'b0;
        force dut.capture_data = 8'h55;
        data_read(1, 8'h55);  // A captured read has no report data.
        force dut.capture_write = 1'b1;
        force dut.capture_data = 8'hA6;
        data_read(0, 8'hA6);  // Next request must clear the previous service error.
        if (native_requests != 0 || cpu_completed || fault)
            $fatal(1, "guard test allowed native issue/completion or false service fault");
        $display("PASS candidate guards: %0d unsupported/halted cases, %0d capture data responses, no native requests", guard_checks, data_checks);
        $finish;
    end
    initial begin #100000; $fatal(1, "guard test watchdog"); end
endmodule
