// Bounded diagnostic candidate. This is not a complete Gemini implementation.
`timescale 1ns/1ps
module card_candidate (
    input wire clk,
    input wire por_n,
    input wire req_valid,
    output wire req_ready,
    input wire [5:0] req_offset,
    input wire req_word,
    input wire req_write,
    input wire [15:0] req_wdata,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [15:0] rsp_rdata,
    output wire rsp_error,
    output wire mem_valid,
    input wire mem_ready,
    output wire mem_write,
    output wire [16:0] mem_addr,
    output wire [15:0] mem_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rdata,
    output reg fault,
    output wire boundary,
    output wire [15:0] cpu_address,
    output reg capture_valid,
    output reg [7:0] capture_status,
    output reg [15:0] capture_address,
    output reg [7:0] capture_data,
    output reg [31:0] capture_count,
    output reg [31:0] cpu_completed
);
    wire [7:0] control;
    wire host_ready, host_error;
    wire [15:0] host_index;
    wire [1:0] master_valid, master_ready, master_write, master_rsp_valid, master_rsp_ready;
    wire [17:0] host_addr;
    wire [15:0] host_wdata, master_rdata;
    wire [1:0] host_be;
    wire host_mem_rsp_ready, denied, drained;
    wire ack, read_release, address_read, command_write, mask_write, keyboard_write;
    wire sidefx_valid, sidefx_word, sidefx_write;
    wire [5:0] sidefx_offset;
    wire [15:0] sidefx_wdata;
    reg cpu_running, start_pending, armed, report_mode;
    reg [7:0] reset_mask, keyboard;
    reg permitted, capture_reset, capture_display, capture_read_release;
    reg capture_address_release, capture_write, service_error;
    wire cpu_valid, cpu_write, cpu_sync, vector_pull, cpu_halted, high_read, high_write;
    wire [16:0] ram_address;
    wire [7:0] cpu_wdata;
    wire cpu_ready;
    reg [7:0] cpu_rdata;
    reg cpu_memory_wait;
    wire is_display = cpu_write && (cpu_address == 16'h0400 || cpu_address == 16'h0800 ||
                                   cpu_address == 16'h2000 || cpu_address == 16'h4000);
    wire reset_vector = vector_pull && cpu_address == 16'hFFFC;
    wire io_trap = cpu_address == 16'hC07D || cpu_address == 16'hC0E9 ||
                   cpu_address == 16'hC0E8 || cpu_address == 16'hC0A0;
    wire trap = reset_vector || io_trap || (is_display && control[1:0] == 0);
    wire io_space = cpu_address >= 16'hC000 && cpu_address < 16'hD000;
    wire allowed_io = io_trap || (cpu_write && (cpu_address == 16'hC004 || cpu_address == 16'hC005)) ||
                      (!cpu_write && (cpu_address == 16'hC000 || cpu_address == 16'hC010 ||
                                      cpu_address == 16'hC019));
    wire [17:0] physical = cpu_address >= 16'hFFFA
        ? 18'h23FFA + {2'b0, cpu_address} - 18'h0FFFA : {1'b0, ram_address};
    wire unsupported_cpu = (io_space && !allowed_io) ||
                           (!io_space && cpu_address >= 16'hC000 &&
                            (cpu_address < 16'hFFFA || cpu_write));
    wire runnable = cpu_valid && cpu_running && !start_pending && !boundary && !fault && !unsupported_cpu;
    wire released = (!trap && !capture_valid) || permitted;
    // ACK after an address release waits for the CPU's next report capture.
    wire hold_ack = req_write && !req_word && (req_offset == 6'h0C || req_offset == 6'h19)
                    && cpu_running && !capture_valid && !boundary && !fault;
    assign req_ready = host_ready && !hold_ack;
    assign rsp_error = host_error || service_error;
    assign boundary = cpu_valid && cpu_sync && cpu_address == 16'h202F;
    assign master_valid[1] = runnable && released && !io_space && !cpu_memory_wait;
    assign master_write[1] = cpu_write;
    assign master_rsp_ready[1] = cpu_memory_wait;
    assign cpu_ready = runnable && released &&
                       (io_space ? allowed_io : (cpu_memory_wait && master_rsp_valid[1]));
    assign master_rsp_ready[0] = host_mem_rsp_ready;

    card_host_registers host (
        .clk(clk), .reset(!por_n), .req_valid(req_valid && !hold_ack), .req_ready(host_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(host_error),
        .mem_req_valid(master_valid[0]), .mem_req_ready(master_ready[0]),
        .mem_req_addr(host_addr), .mem_req_write(master_write[0]),
        .mem_req_wdata(host_wdata), .mem_req_be(host_be),
        .mem_rsp_valid(master_rsp_valid[0]), .mem_rsp_ready(host_mem_rsp_ready),
        .mem_rsp_rdata(master_rdata), .mem_rsp_denied(denied), .control(control), .index(host_index),
        .capture_status(capture_valid ? capture_status : 8'b0),
        .capture_address(capture_valid ? capture_address : 16'b0), .capture_data(capture_data),
        .keyboard_status({keyboard[7], 7'b0}), .opaque08(8'b0),
        .sidefx_valid(sidefx_valid), .sidefx_offset(sidefx_offset), .sidefx_word(sidefx_word),
        .sidefx_write(sidefx_write), .sidefx_wdata(sidefx_wdata),
        .ack_write(ack), .read_release_write(read_release), .capture_address_read(address_read),
        .control_write(), .command_write(command_write), .mask_write(mask_write),
        .keyboard_write(keyboard_write)
    );
    card_cpu_bus processor (
        .clk(clk), .reset(!por_n || !cpu_running), .ready(cpu_ready), .read_data(cpu_rdata),
        .irq_n(1'b1), .nmi_n(1'b1), .valid(cpu_valid), .address(cpu_address),
        .ram_address(ram_address), .write(cpu_write), .write_data(cpu_wdata), .sync(cpu_sync),
        .vector_pull(vector_pull), .halted(cpu_halted), .high_ram_read(high_read),
        .high_ram_write(high_write)
    );
    card_memory_arbiter memory (
        .clk(clk), .por_n(por_n), .reset_request(1'b0), .drained(drained),
        .req_valid(master_valid), .req_ready(master_ready), .req_write(master_write),
        .req_write_allowed(2'b11), .host_addr(host_addr), .card_addr(physical),
        .host_wdata(host_wdata), .card_wdata({cpu_wdata, cpu_wdata}),
        .host_be(host_be), .card_be(physical[0] ? 2'b10 : 2'b01),
        .rsp_valid(master_rsp_valid), .rsp_ready(master_rsp_ready),
        .rsp_rdata(master_rdata), .rsp_denied(denied),
        .mem_valid(mem_valid), .mem_ready(mem_ready), .mem_write(mem_write),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rdata(mem_rdata)
    );

    always @* begin
        cpu_rdata = physical[0] ? master_rdata[15:8] : master_rdata[7:0];
        case (cpu_address)
            16'hC07D: cpu_rdata = 8'hA5;
            16'hC0E8, 16'hC0E9, 16'hC0A0: cpu_rdata = 8'hA5;
            16'hC000: cpu_rdata = keyboard;
            16'hC010: cpu_rdata = {control[7], 7'b0};
            16'hC019: cpu_rdata = {control[6], 7'b0};
            default: ;
        endcase
    end

    always @(posedge clk) begin
        if (!por_n) begin
            cpu_running <= 0;
            start_pending <= 0;
            armed <= 0;
            report_mode <= 0;
            reset_mask <= 0;
            keyboard <= 0;
            capture_valid <= 0;
            capture_status <= 0;
            capture_address <= 0;
            capture_data <= 0;
            capture_count <= 0;
            capture_reset <= 0;
            capture_display <= 0;
            capture_read_release <= 0;
            capture_address_release <= 0;
            capture_write <= 0;
            service_error <= 0;
            permitted <= 0;
            cpu_memory_wait <= 0;
            cpu_completed <= 0;
            fault <= 0;
        end else begin
            if (req_valid && req_ready)
                service_error <= !req_write && !req_word && req_offset == 6'h0C &&
                                 (!capture_valid || !capture_write);
            if (master_valid[1] && master_ready[1]) cpu_memory_wait <= 1;
            if (master_rsp_valid[1] && master_rsp_ready[1]) begin
                cpu_memory_wait <= 0;
                if (denied) fault <= 1;
            end
            if (start_pending && drained && !cpu_memory_wait) begin
                cpu_running <= 1;
                start_pending <= 0;
            end
            if (cpu_running && !start_pending && !boundary &&
                (cpu_halted || (cpu_valid && unsupported_cpu))) fault <= 1;
            if (runnable && trap && !permitted && !capture_valid) begin
                capture_valid <= 1;
                capture_count <= capture_count + 1;
                capture_address <= cpu_address;
                capture_data <= cpu_write ? cpu_wdata : 0;
                capture_reset <= reset_vector;
                capture_display <= is_display;
                capture_read_release <= cpu_address == 16'hC07D && !cpu_write;
                capture_address_release <= is_display && report_mode;
                capture_write <= cpu_write;
                if (reset_vector) capture_status <= 8'h80;
                else if (cpu_address == 16'hC07D) capture_status <= cpu_write ? 8'hE0 : 8'hE1;
                else if (cpu_address == 16'hC0E9) capture_status <= 8'h38;
                else if (cpu_address == 16'hC0E8) capture_status <= 8'h28;
                else if (cpu_address == 16'hC0A0) capture_status <= cpu_write ? 8'h08 : 8'h09;
                else begin
                    case (cpu_address)
                        16'h0400: capture_status <= 8'h02 | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        16'h0800: capture_status <= 8'h22 | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        16'h2000: capture_status <= 8'h04 | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        16'h4000: capture_status <= 8'h24 | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        default: fault <= 1;
                    endcase
                end
            end
            if (cpu_ready) begin
                cpu_completed <= cpu_completed + 1;
                permitted <= 0;
                if (!cpu_write && cpu_address == 16'hC010) keyboard[7] <= 0;
            end
            if (mask_write) reset_mask <= sidefx_wdata[7:0];
            if (keyboard_write) keyboard <= sidefx_wdata[7:0];
            if (command_write) begin
                if ((sidefx_word && sidefx_wdata == 16'h0802) ||
                    (!sidefx_word && sidefx_wdata[7:0] == 8'h80 && reset_mask == 8'hFC)) begin
                    // This bounded loader accepts reset only while memory is quiescent.
                    if (!drained || cpu_memory_wait) fault <= 1;
                    else begin
                        cpu_running <= 0;
                        start_pending <= !sidefx_word;
                        armed <= 0;
                        report_mode <= 0;
                        capture_valid <= 0;
                        permitted <= 0;
                        keyboard <= 0;
                    end
                end else if (!sidefx_word && sidefx_wdata[7:0] == 8'h88) begin
                    if ((capture_valid && capture_reset) || armed) begin
                        armed <= 1;
                        report_mode <= 0;
                    end else fault <= 1;
                end else if (!sidefx_word && sidefx_wdata[7:0] == 8'h98 && armed)
                    report_mode <= 1;
                else fault <= 1;
            end
            if (ack || read_release || (address_read && capture_valid && capture_address_release)) begin
                if (capture_valid) begin
                    if (sidefx_write && sidefx_wdata[7:0] != 0) fault <= 1;
                    else if ((read_release != capture_read_release && !address_read) ||
                             (capture_reset && !armed)) fault <= 1;
                    else begin
                        capture_valid <= 0;
                        permitted <= 1;
                    end
                end else if (cpu_running && (ack || read_release)) fault <= 1;
            end
        end
    end
endmodule
