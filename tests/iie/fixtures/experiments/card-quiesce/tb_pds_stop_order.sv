`timescale 1ns/1ps
module tb_pds_stop_order;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0, host_reset = 0, stop_request = 0;
    wire cpu_stopped, pds_stopped, endpoint_drained;
    reg [31:0] pds_address = 0;
    wire [2:0] pds_fc = 3'b001;
    reg pds_as_n = 1, pds_uds_n = 1, pds_lds_n = 1;
    wire pds_rw = 0;
    reg [15:0] pds_write_data = 0;
    wire claim, dtack_n, error, fault, boundary, capture_valid;
    wire [15:0] pds_read_data, card_cpu_address, capture_address;
    wire [7:0] capture_status, capture_data;
    wire [31:0] capture_count, cpu_completed;
    wire mem_valid, mem_write, mem_rsp_ready;
    wire [16:0] mem_addr;
    wire [15:0] mem_wdata;
    wire mem_ready = !pending;
    reg mem_rsp_valid = 0;
    reg [15:0] mem_rdata = 0;
    reg pending = 0;
    integer delay_count = 0;
    card_pds_candidate dut (.*);
    always @(posedge clk) begin
        if (!por_n) begin
            pending <= 0;
            mem_rsp_valid <= 0;
        end else begin
            if (mem_valid && mem_ready) begin
                if (mem_write) $fatal(1, "unexpected fixture write");
                pending <= 1;
                delay_count <= 6;
                case (mem_addr)
                    17'h11FFE: mem_rdata <= 16'h0200;
                    17'h00100: mem_rdata <= 16'hE8AD;
                    17'h00101: mem_rdata <= 16'hEAC0;
                    default: mem_rdata <= 16'hEAEA;
                endcase
            end
            if (pending && !mem_rsp_valid) begin
                if (delay_count == 0) mem_rsp_valid <= 1;
                else delay_count <= delay_count - 1;
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 0;
                pending <= 0;
            end
        end
    end
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task begin_write(input [5:0] offset, input [7:0] value);
        begin
            @(negedge clk);
            pds_address = 32'h00E00000 + {26'b0, offset[5:1], 1'b0};
            pds_uds_n = offset[0]; pds_lds_n = !offset[0];
            pds_write_data = {value, value}; pds_as_n = 0;
        end
    endtask
    task end_write;
        begin
            while (dtack_n) tick;
            if (error) $fatal(1, "PDS write response error");
            @(negedge clk); pds_as_n = 1;
            tick; tick;
        end
    endtask
    task write_register(input [5:0] offset, input [7:0] value);
        begin begin_write(offset, value); end_write; end
    endtask
    integer held_cycles = 0;
    initial begin
        tick; tick; por_n = 1; tick;
        write_register(6'h21, 8'hFC);
        write_register(6'h20, 8'h80);
        while (!capture_valid) tick;
        write_register(6'h20, 8'h88);
        write_register(6'h0C, 0);
        begin_write(6'h0C, 0);
        while (!(dut.req_valid && dut.card.hold_ack)) tick;
        @(negedge clk); stop_request = 1;
        while (dtack_n) begin
            tick;
            held_cycles = held_cycles + 1;
            if (cpu_stopped || pds_stopped || dut.card.stop_request)
                $fatal(1, "CPU stopped before capture-dependent PDS ACK finished");
        end
        if (held_cycles < 2 || capture_count < 2 || fault || error)
            $fatal(1, "capture-dependent PDS ACK did not complete normally");
        repeat (4) begin
            tick;
            if (pds_stopped || cpu_stopped || dtack_n)
                $fatal(1, "PDS DONE stop ordering changed before AS release");
        end
        @(negedge clk); pds_as_n = 1;
        while (!cpu_stopped || !pds_stopped || !endpoint_drained) tick;
        if (fault) $fatal(1, "wrapper ordering fault");
        $display("PASS actual WDC capture-dependent PDS ACK drains before CPU stop (%0d clocks)", held_cycles);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "wrapper ordering watchdog cpu=%h captures=%d hold=%b", card_cpu_address, capture_count, dut.card.hold_ack);
    end
endmodule
