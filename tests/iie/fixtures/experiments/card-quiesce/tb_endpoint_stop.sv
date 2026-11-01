`timescale 1ns/1ps
module tb_endpoint_stop;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0, stop_request = 0;
    wire stopped, endpoint_drained;
    reg req_valid = 0, req_word = 0, req_write = 0, rsp_ready = 1;
    reg [5:0] req_offset = 0;
    reg [15:0] req_wdata = 0;
    wire req_ready, rsp_valid, rsp_error;
    wire [15:0] rsp_rdata;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    reg mem_ready = 0, mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 16'h0200;
    wire fault, boundary, capture_valid;
    wire [15:0] cpu_address, capture_address;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    card_candidate dut (.*);

    reg p_reset = 1, p_stop = 0, p_as_n = 1;
    reg p_strobes_n = 1;
    reg [31:0] p_address = 32'h00E00010;
    reg [15:0] p_write_data = 16'hA65C;
    reg p_req_ready = 0, p_rsp_valid = 0;
    wire p_stopped, p_claim, p_dtack_n, p_error, p_req_valid, p_rsp_ready;
    wire [15:0] p_read_data, p_req_wdata;
    wire [5:0] p_req_offset;
    wire p_req_word, p_req_write;
    card_pds_adapter pds (
        .clk(clk), .reset(p_reset), .stop_request(p_stop), .stopped(p_stopped),
        .cpu_address(p_address), .cpu_fc(3'b001), .cpu_as_n(p_as_n),
        .cpu_uds_n(p_strobes_n), .cpu_lds_n(p_strobes_n), .cpu_rw(1'b0),
        .cpu_write_data(p_write_data), .claim(p_claim), .dtack_n(p_dtack_n),
        .cpu_read_data(p_read_data), .error(p_error), .req_valid(p_req_valid),
        .req_ready(p_req_ready), .req_offset(p_req_offset), .req_word(p_req_word),
        .req_write(p_req_write), .req_wdata(p_req_wdata), .rsp_valid(p_rsp_valid),
        .rsp_ready(p_rsp_ready), .rsp_rdata(16'h1234), .rsp_error(1'b0)
    );
    integer cpu_accepts = 0, cpu_responses = 0, p_accepts = 0, p_responses = 0;
    always @(posedge clk) begin
        if (por_n && dut.master_valid[1] && dut.master_ready[1]) cpu_accepts <= cpu_accepts + 1;
        if (por_n && dut.master_rsp_valid[1] && dut.master_rsp_ready[1]) cpu_responses <= cpu_responses + 1;
        if (p_req_valid && p_req_ready) p_accepts <= p_accepts + 1;
        if (p_rsp_valid && p_rsp_ready) p_responses <= p_responses + 1;
    end
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task host_reg(input [5:0] offset, input [15:0] value);
        begin
            @(negedge clk);
            req_valid = 1; req_write = 1; req_word = 0;
            req_offset = offset; req_wdata = value;
            #1;
            while (!req_ready) tick;
            tick;
            req_valid = 0;
            while (!rsp_valid) tick;
            if (rsp_error) $fatal(1, "host register setup error");
            tick;
        end
    endtask
    task backend_complete;
        begin
            while (!mem_valid) tick;
            @(negedge clk); mem_ready = 1;
            tick; mem_ready = 0;
            if (!mem_rsp_ready) $fatal(1, "missing backend response readiness");
            @(negedge clk); mem_rsp_valid = 1;
            tick; mem_rsp_valid = 0;
        end
    endtask
    reg [28:0] offered;
    reg [31:0] completed_before, captures_before;
    reg [23:0] capture_before;
    reg [15:0] cpu_address_before;
    integer accepts_before, responses_before, stage = 0;
    initial begin
        tick; tick; por_n = 1; p_reset = 0; tick;
        host_reg(6'h21, 16'h00FC);
        host_reg(6'h20, 16'h0080);
        while (!capture_valid) begin
            if (mem_valid) backend_complete;
            else tick;
        end
        if (capture_status != 8'h80 || capture_address != 16'hFFFC)
            $fatal(1, "actual WDC reset-vector trap absent");
        captures_before = capture_count;
        capture_before = {capture_status, capture_address};
        @(negedge clk); stop_request = 1;
        repeat (8) begin
            tick;
            if (!stopped || !endpoint_drained || !capture_valid ||
                capture_count != captures_before || {capture_status, capture_address} != capture_before)
                $fatal(1, "stop lost pending WDC capture");
        end
        stop_request = 0; tick;
        if (!capture_valid || {capture_status, capture_address} != capture_before)
            $fatal(1, "resume lost pending WDC capture");
        host_reg(6'h20, 16'h0088);
        host_reg(6'h0C, 0);
        stage = 1;
        while (!mem_valid) tick;
        // Hold the actual CPU backend request while the host queues a read.
        @(negedge clk);
        req_valid = 1; req_write = 0; req_word = 0; req_offset = 6'h10;
        #1;
        while (!req_ready) tick;
        tick; req_valid = 0;
        stage = 2;
        backend_complete;
        stage = 3;
        while (!(dut.master_valid[1] && !dut.master_ready[1] && mem_valid && !dut.memory.owner)) tick;
        @(negedge clk); stop_request = 1;
        offered = {dut.cpu_offer_addr, dut.cpu_offer_write, dut.cpu_offer_wdata, dut.master_valid[1], dut.master_write[1]};
        completed_before = cpu_completed;
        cpu_address_before = cpu_address;
        accepts_before = cpu_accepts;
        responses_before = cpu_responses;
        repeat (8) begin
            tick;
            if (stopped || endpoint_drained || !dut.master_valid[1] ||
                {dut.cpu_offer_addr, dut.cpu_offer_write, dut.cpu_offer_wdata, dut.master_valid[1], dut.master_write[1]} !== offered)
                $fatal(1, "stop withdrew or changed backpressured CPU request");
        end
        backend_complete;
        while (cpu_accepts == accepts_before) tick;
        if (stopped) $fatal(1, "CPU stopped before accepted response");
        backend_complete;
        while (!stopped || !endpoint_drained) tick;
        if (cpu_accepts != accepts_before + 1 || cpu_responses != responses_before + 1 ||
            cpu_completed != completed_before + 1 || cpu_address == cpu_address_before)
            $fatal(1, "CPU accepted response did not advance exactly once");
        repeat (8) begin
            tick;
            if (!stopped || mem_valid || dut.master_valid[1] || cpu_completed != completed_before + 1)
                $fatal(1, "CPU advanced after stop acknowledgment");
        end
        if (fault) $fatal(1, "candidate fault");

        @(negedge clk); p_as_n = 0;
        tick;
        @(negedge clk); p_stop = 1;
        repeat (8) begin
            tick;
            if (!p_claim || p_stopped || p_req_valid)
                $fatal(1, "PDS stop withdrew pre-strobe claim");
        end
        p_strobes_n = 0; tick;
        p_address = 32'h12345678; p_write_data = 0;
        repeat (8) begin
            tick;
            if (!p_req_valid || !p_claim || p_stopped ||
                {p_req_offset, p_req_word, p_req_write, p_req_wdata} !== {6'h10, 1'b1, 1'b1, 16'hA65C})
                $fatal(1, "PDS stop changed REQUEST offer");
        end
        p_req_ready = 1; tick; p_req_ready = 0;
        repeat (8) begin
            tick;
            if (!p_rsp_ready || p_stopped || !p_claim || !p_dtack_n)
                $fatal(1, "PDS RESPONSE stopped prematurely");
        end
        p_rsp_valid = 1; tick; p_rsp_valid = 0;
        repeat (8) begin
            tick;
            if (p_stopped || p_dtack_n || !p_claim)
                $fatal(1, "PDS DONE did not wait for AS release");
        end
        p_as_n = 1; tick;
        if (!p_stopped || p_claim) $fatal(1, "PDS failed to stop after AS release");
        p_as_n = 0; tick;
        if (p_claim || p_req_valid || !p_stopped) $fatal(1, "PDS admitted new work while stopped");
        p_as_n = 1; p_stop = 0; tick;
        p_address = 32'h00E00010; p_write_data = 16'hA65C;
        p_as_n = 0; tick; p_req_ready = 1; tick; p_req_ready = 0;
        p_reset = 1; tick;
        if (!p_rsp_ready || !p_dtack_n || p_claim) $fatal(1, "accepted PDS abort did not drain");
        p_rsp_valid = 1; tick; p_rsp_valid = 0;
        p_reset = 0; p_as_n = 1; tick;
        if (p_req_valid || p_rsp_ready || !p_dtack_n || p_accepts != 2 || p_responses != 2)
            $fatal(1, "PDS abort completion mismatch");
        $display("PASS actual WDC capture stop/resume, stalled CPU offer, exact response advance, PDS stop and host abort");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "endpoint watchdog stage=%d cpu=%h capture=%b mem=%b arb=%d pds=%d", stage, cpu_address, capture_valid, mem_valid, dut.memory.state, pds.state);
    end
endmodule
