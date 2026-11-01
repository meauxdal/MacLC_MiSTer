`timescale 1ns/1ps
module tb_card_irq;
    parameter SUPPRESS_NMI = 0, SUPPRESS_IRQ = 0, NMI_DELAY = 0, IRQ_DELAY = 0;
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
    reg mem_ready = 0, mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    card_irq_candidate #(.SUPPRESS_NMI(SUPPRESS_NMI), .SUPPRESS_IRQ(SUPPRESS_IRQ),
                         .NMI_DELAY(NMI_DELAY), .IRQ_DELAY(IRQ_DELAY)) dut (.*);
    reg [15:0] memory [0:131071];
    reg [7:0] expected [0:262143];
    reg backend_busy = 0, backend_write;
    reg [16:0] backend_addr;
    reg [15:0] backend_data;
    integer ticks = 0, delay_scale = 1, countdown = 0, backend_count = 0;
    integer stimulus, traces, events, status, writing, word_access, offset, value, gap;
    integer i, last_capture = 0, nmi_vectors = 0, irq_vectors = 0, rtis = 0, pushes = 0, irq_error;
    integer opcode_events = 0, firmware_reads = 0, expected_error = 0;
    reg [1023:0] stimulus_path, expected_path, trace_path, events_path;
    reg [15:0] answer;
    always @(negedge clk)
        mem_ready = por_n && !backend_busy && !mem_rsp_valid && ticks % 5 != 0;
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 1000000) $fatal(1, "IRQ test watchdog");
        if (por_n && fault) $fatal(1, "IRQ candidate fault address=%h capture=%h", cpu_address, capture_address);
        if (mem_valid && mem_ready) begin
            if (backend_busy || mem_rsp_valid) $fatal(1, "overlapping memory operation");
            backend_busy <= 1;
            backend_write <= mem_write;
            backend_addr <= mem_addr;
            backend_data <= mem_wdata;
            countdown <= 1 + delay_scale * (backend_count % 8);
            backend_count <= backend_count + 1;
        end
        if (backend_busy) begin
            if (countdown == 0) begin
                if (backend_write) memory[backend_addr] <= backend_data;
                mem_rdata <= backend_write ? 0 : memory[backend_addr];
                mem_rsp_valid <= 1;
                backend_busy <= 0;
            end else countdown <= countdown - 1;
        end
        if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 0;
        if (capture_count != last_capture) begin
            if (!capture_valid) $fatal(1, "lost capture");
            $fdisplay(traces, "%02x %04x %02x", capture_status, capture_address, capture_data);
            last_capture = capture_count;
        end
        if (dut.opcode02_complete) begin
            opcode_events = opcode_events + 1;
            $fdisplay(events, "O %04x %02x", cpu_address, dut.cpu_rdata);
        end
        if (dut.cpu_ready) begin
            if (dut.vector_pull) begin
                $fdisplay(events, "V %04x %02x", cpu_address, dut.cpu_rdata);
                if (cpu_address == 16'hFFFA) nmi_vectors = nmi_vectors + 1;
                if (cpu_address == 16'hFFFE) irq_vectors = irq_vectors + 1;
            end
            if (dut.firmware_read) begin
                if (dut.physical < 18'h25000 || dut.physical > 18'h25006 || dut.cpu_write ||
                    (dut.physical == 18'h25006 && dut.cpu_sync))
                    $fatal(1, "NMI firmware mapping escaped payload/dummy boundary");
                firmware_reads = firmware_reads + 1;
                $fdisplay(events, "F %04x %05x %02x", cpu_address, dut.physical, dut.cpu_rdata);
            end
            if (opcode_events != 0 && dut.cpu_write && cpu_address >= 16'h0100 && cpu_address < 16'h0200) begin
                pushes = pushes + 1;
                $fdisplay(events, "S %04x %02x", cpu_address, dut.cpu_wdata);
            end
            if (dut.rti_done) begin
                rtis = rtis + 1;
                $fdisplay(events, "T %04x", {dut.cpu_rdata, dut.processor.cpu.dl});
            end
        end
    end
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task access(input wr, input word_arg, input [5:0] off,
                input [15:0] data, output [15:0] result);
        begin
            @(negedge clk);
            req_valid = 1;
            req_write = wr;
            req_word = word_arg;
            req_offset = off;
            req_wdata = data;
            @(posedge clk);
            while (!req_ready) @(posedge clk);
            @(negedge clk);
            req_valid = 0;
            while (!rsp_valid) @(negedge clk);
            result = rsp_rdata;
            if (rsp_error) $fatal(1, "host service error offset=%h", off);
            repeat (2) begin
                @(negedge clk);
                if (!rsp_valid || rsp_rdata !== result || rsp_error) $fatal(1, "host response backpressure");
            end
            rsp_ready = 1;
            @(negedge clk);
            rsp_ready = 0;
        end
    endtask
    task ack;
        begin access(1, 0, 6'h0C, 0, answer); end
    endtask
    task poll(output integer error_arg);
        integer n;
        begin
            access(0, 0, 1, 0, answer); // Discard the first status sample.
            error_arg = 2;
            for (n = 0; n < 1001 && error_arg != 0; n = n + 1) begin
                access(0, 0, 1, 0, answer);
                if (answer[7:0] != 0) error_arg = 0;
            end
        end
    endtask
    task interrupt_helper(output integer error_arg);
        integer wait_error;
        begin
            ack;
            poll(wait_error);
            error_arg = 11;
            if (wait_error == 0) begin
                access(0, 0, 6'h0C, 0, answer);
                if (answer == 2) begin
                    ack;
                    access(0, 0, 6'h20, 0, answer);
                    access(1, 0, 6'h20, answer | 16'h0020, answer);
                    poll(wait_error);
                    access(0, 0, 6'h20, 0, answer);
                    access(1, 0, 6'h20, answer & 16'h00DF, answer);
                    error_arg = 12;
                    if (wait_error == 0) begin
                        ack;
                        poll(wait_error);
                        if (wait_error == 0) error_arg = 0;
                    end
                end
            end
        end
    endtask
    initial begin
        if (!$value$plusargs("stimulus=%s", stimulus_path) ||
            !$value$plusargs("expected=%s", expected_path) ||
            !$value$plusargs("trace=%s", trace_path) || !$value$plusargs("events=%s", events_path))
            $fatal(1, "missing test files");
        if ($value$plusargs("delay=%d", delay_scale)) begin end
        if ($value$plusargs("error=%d", expected_error)) begin end
        for (i = 0; i < 131072; i = i + 1) memory[i] = 0;
        $readmemh(expected_path, expected);
        stimulus = $fopen(stimulus_path, "r");
        traces = $fopen(trace_path, "w");
        events = $fopen(events_path, "w");
        if (stimulus == 0 || traces == 0 || events == 0) $fatal(1, "test file open");
        repeat (3) tick;
        por_n = 1;
        while (!$feof(stimulus)) begin
            status = $fscanf(stimulus, "%d %d %d %d %d\n", writing, word_access, offset, value, gap);
            if (status == 5) begin
                repeat (gap) @(negedge clk);
                access(writing != 0, word_access != 0, offset[5:0], value[15:0], answer);
                if (writing == 0 && answer !== value[15:0]) $fatal(1, "prefix host read mismatch at%h", offset);
            end else if (status != -1) $fatal(1, "bad prefix stimulus");
        end
        if (!capture_valid || capture_status != 8'hE0 || capture_address != 16'hC07D || capture_data != 0 || capture_count != 39)
            $fatal(1, "prefix does not leave the final VBL report pending");
        interrupt_helper(irq_error);
        if (irq_error != expected_error) $fatal(1, "interrupt helper expected%0d got%0d", expected_error, irq_error);
        if (opcode_events != 1) $fatal(1, "generic opcode event repeated/missing");
        if (irq_error == 0) begin
            if (!capture_valid || capture_status != 8'hE0 || capture_data != 1 ||
                cpu_address != 16'hC07D || memory[16'h200A / 2][7:0] != 1)
                $fatal(1, "main report/counter did not follow actual IRQ");
            ack;
            repeat (200) tick;
            if (!boundary || cpu_address != 16'h203A || capture_valid || capture_count != 42 ||
                dut.processor.cpu.reg_s != 8'hFD || nmi_vectors != 1 || irq_vectors != 1 ||
                rtis != 2 || pushes != 6 || firmware_reads < 6 || dut.nmi_overlay || dut.irq_level)
                $fatal(1, "interrupt completion/vector/stack/overlay invariant");
        end else begin
            repeat (100) tick;
            if (memory[16'h200A / 2][7:0] != 0 || irq_vectors != 0 || dut.irq_level || dut.nmi_overlay || capture_valid)
                $fatal(1, "suppressed/delayed interrupt manufactured progress");
            if (irq_error == 11 && (nmi_vectors != 0 || rtis != 0 || pushes != 0 || firmware_reads != 0))
                $fatal(1, "missing NMI nevertheless serviced firmware");
            if (irq_error == 12 && (nmi_vectors != 1 || rtis != 1 || pushes != 3))
                $fatal(1, "missing IRQ damaged NMI completion");
        end
        if (backend_busy || mem_rsp_valid || dut.cpu_memory_wait) begin
            // Failed helpers leave the CPU polling; stop after an in-flight read drains.
            if (irq_error == 0) $fatal(1, "successful endpoint not drained");
        end
        for (i = 0; i < 262144; i = i + 1) begin
            if (i != 32'h01FB && i != 32'h01FC && i != 32'h01FD && i != 32'h200A &&
                (i[0] ? memory[i / 2][15:8] : memory[i / 2][7:0]) !== expected[i])
                $fatal(1, "unexpected memory change byte%h", i);
        end
        if (irq_error == 11 && memory[16'h01FA / 2] !== {expected[18'h01FB], expected[18'h01FA]})
            $fatal(1, "missing NMI changed stack flags");
        $display("PASS IRQ system error=%0d captures=%0d generic02=%0d NMI=%0d IRQ=%0d RTI=%0d pushes=%0d firmware_reads=%0d delay=%0d", irq_error, capture_count, opcode_events, nmi_vectors, irq_vectors, rtis, pushes, firmware_reads, delay_scale);
        $fclose(stimulus);
        $fclose(traces);
        $fclose(events);
        $finish;
    end
endmodule
