// Experimental card runtime; physical control semantics remain under test.
`timescale 1ns/1ps
module card_irq_candidate #(
    parameter bit IGNORE_ZP_CONTEXT = 0, ALIAS_LC_BANKS = 0, IGNORE_FW_OVERLAY = 0,
    parameter bit FIXED_CX = 0,
    parameter [2:0] GAME_INPUTS = 3'b000,
    parameter [7:0] FLOATING_DATA = 8'h00,
    parameter bit PACE_FAST = 0,
    parameter integer PACE_CLOCK_HZ = 32500000,
    parameter bit SUPPRESS_NMI = 0, SUPPRESS_IRQ = 0,
    parameter integer NMI_DELAY = 0, IRQ_DELAY = 0,
    parameter bit IGNORE_AUX_INHIBIT = 0, IGNORE_FW_PROTECT = 0, IGNORE_SOFTSWITCH = 0,
    parameter [7:0] SOFTSWITCH_STUCK_MASK = 8'h00
) (
    input wire clk,
    input wire runtime_mode,
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
    output reg [15:0] instruction_address = 0,
    output reg capture_valid,
    output reg [7:0] capture_status,
    output reg [15:0] capture_address,
    output reg [7:0] capture_data,
    output reg [31:0] capture_count,
    output reg [31:0] cpu_completed,
    output wire [3:0] debug_state,
    output wire [71:0] debug_trace
);
    assign debug_state = {monitor_active, cpu_running, reset_pending, armed};
    reg [7:0] start_mask;
    reg start_override;
    reg [2:0] start_count;
    reg [3:0] first_fault;
    reg [55:0] command_context;
    assign debug_trace = {command_context, start_mask, start_override, start_count, first_fault};
    always @(posedge clk) begin
        if (!por_n) instruction_address <= 0;
        else if (cpu_ready && cpu_sync) instruction_address <= cpu_address;
    end
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
    reg nmi_pending, nmi_overlay, irq_level;
    reg [31:0] nmi_delay_left, irq_delay_left;
    wire rti_done;
    reg cpu_running, start_pending, armed, report_mode;
    reg runtime_paused, runtime_refresh;
    reg reset_pending, reset_restart;
    wire reset_command = command_write && ((sidefx_word && sidefx_wdata == 16'h0802) ||
        (!sidefx_word && sidefx_wdata[7:0] == 8'h80 && (reset_mask == 8'hFC || !cpu_running)));
    wire reset_stopping = reset_pending || reset_command;
    wire reset_commit = reset_pending && drained && !cpu_memory_wait;
    reg [7:0] reset_mask, keyboard;
    reg permitted, capture_reset, capture_display, capture_read_release;
    reg capture_address_release, capture_write;
    wire cpu_valid, cpu_write, cpu_sync, vector_pull, cpu_halted, high_read, high_write;
    wire [16:0] ram_address;
    wire [7:0] cpu_wdata;
    reg internal_rom, monitor_active;
    reg slot3_rom, internal_c8;
    reg [7:0] card_mode;
    reg [7:0] host_return;
    wire mode_store80, mode_page2, mode_text, mode_mixed, mode_hires, mode_altchar, mode_col80;
    card_display_state display_state (
        .clk(clk), .reset(!por_n || !cpu_running), .valid(cpu_valid), .complete(cpu_ready),
        .address(cpu_address), .write(cpu_write), .aux(ram_address[16]), .double_hires(1'b0), .motor(1'b0),
        .altchar(mode_altchar), .text_mode(mode_text), .hires(mode_hires), .annunciator3(),
        .col80(mode_col80), .mixed(mode_mixed),
        .page2(mode_page2), .store80(mode_store80), .active_page2(),
        .text_page_active(), .hires_page_active(), .display_trap(), .io_trap()
    );
    wire receiver_read = monitor_active && nmi_overlay && !cpu_write &&
                         cpu_address >= 16'hD000 && cpu_address < 16'hD066;
    wire internal_cx = internal_rom ||
        (cpu_address[15:8] == 8'hC3 && !slot3_rom) ||
        (cpu_address >= 16'hC800 && internal_c8);
    wire monitor_read = monitor_active && !cpu_write &&
        ((cpu_address >= 16'hD000 && !high_read) ||
         (cpu_address >= 16'hC100 && cpu_address < 16'hD000 && (FIXED_CX || internal_cx)));
    wire external_cx_read = monitor_active && !cpu_write && cpu_address >= 16'hC100 &&
        cpu_address < 16'hC800 && !internal_cx && !FIXED_CX;
    wire slot3_read = monitor_active && !cpu_write && cpu_address[15:8] == 8'hC3 && !internal_cx && !FIXED_CX;
    wire cfff_read = monitor_active && !cpu_write && cpu_address == 16'hCFFF && !internal_cx && !FIXED_CX;
    wire service_register = cpu_address >= 16'hC078 && cpu_address <= 16'hC07C;
    wire cpu_ready, pace_due;
    card_cycle_pacer #(.CLOCK_HZ(PACE_CLOCK_HZ)) pace (
        .clk(clk), .reset(!por_n || !cpu_running), .fast(1'(PACE_FAST)),
        .complete(pace_due), .due(pace_due)
    );
    wire iwm_selected = cpu_address[15:4] == 12'hC0E;
    wire [7:0] iwm_rdata;
    wire [4:0] iwm_mode;
    wire iwm_motor, iwm_q6, iwm_q7;
    card_iwm_frontend iwm (
        .clk(clk), .reset(!por_n || !cpu_running), .complete(cpu_ready),
        .selected(iwm_selected), .address(cpu_address[3:0]), .write(cpu_write),
        .write_data(cpu_wdata), .drive_data(8'hFF), .drive_sense(1'b1),
        .write_busy(1'b0), .write_underrun(1'b0), .read_data(iwm_rdata),
        .phases(), .motor(iwm_motor), .drive_select(), .q6(iwm_q6), .q7(iwm_q7),
        .mode(iwm_mode), .data_read(), .data_write(), .data_out()
    );
    reg [7:0] cpu_rdata;
    reg cpu_memory_wait;
    wire diagnostic_display = cpu_write && !monitor_active && control[1:0] == 0 &&
        (cpu_address == 16'h0400 || cpu_address == 16'h0800 ||
         cpu_address == 16'h2000 || cpu_address == 16'h4000);
    wire is_display = diagnostic_display || (monitor_active && cpu_write &&
        ((cpu_address >= 16'h0400 && cpu_address < 16'h0800 && reset_mask[5]) ||
         (cpu_address >= 16'h0800 && cpu_address < 16'h0C00 && reset_mask[4])));
    wire reset_vector = vector_pull && cpu_address == 16'hFFFC;
    wire io_trap = service_register || cpu_address == 16'hC07D || cpu_address == 16'hC0E9 ||
                   cpu_address == 16'hC0E8 || cpu_address == 16'hC0A0;
    reg [7:0] display_switches;
    wire display_switch = (cpu_write || (monitor_active && cpu_address >= 16'hC050)) && (cpu_address == 16'hC00F ||
                       cpu_address == 16'hC051 ||
                       cpu_address == 16'hC057 ||
                       cpu_address == 16'hC05F ||
                       cpu_address == 16'hC00D ||
                       cpu_address == 16'hC053 ||
                       cpu_address == 16'hC055 ||
                       cpu_address == 16'hC001 ||
                       cpu_address == 16'hC00E ||
                       cpu_address == 16'hC050 ||
                       cpu_address == 16'hC056 ||
                       cpu_address == 16'hC05E ||
                       cpu_address == 16'hC00C ||
                       cpu_address == 16'hC052 ||
                       cpu_address == 16'hC054 ||
                       cpu_address == 16'hC000);
    wire trap = reset_vector || io_trap || display_switch || is_display;
    wire io_space = cpu_address >= 16'hC000 && cpu_address < 16'hC100;
    wire allowed_io = iwm_selected || (cpu_write && cpu_address == 16'hC028) || cpu_address == 16'hC010 || service_register ||
                      cpu_address == 16'hC015 || cpu_address == 16'hC018 || cpu_address == 16'hC02B ||
                      (cpu_address >= 16'hC01A && cpu_address <= 16'hC01F) ||
                      cpu_address == 16'hC007 || cpu_address == 16'hC006 ||
                      cpu_address == 16'hC00A || cpu_address == 16'hC00B || cpu_address == 16'hC017 ||
                      (cpu_address >= 16'hC061 && cpu_address <= 16'hC063) ||
                      (cpu_address >= 16'hC050 && cpu_address <= 16'hC05F) || io_trap || display_switch || (cpu_write && (cpu_address == 16'hC004 || cpu_address == 16'hC005 ||
                                               cpu_address == 16'hC008 || cpu_address == 16'hC009 ||
                                               cpu_address == 16'hC002 || cpu_address == 16'hC003)) ||
                      (!cpu_write && (cpu_address == 16'hC000 || cpu_address == 16'hC010 ||
                                      cpu_address == 16'hC019 || cpu_address[15:4] == 12'hC08));
    // Candidate controls, bounded to the original zero-page and E000 tests.
    wire aux_inhibit = control[2] && !IGNORE_AUX_INHIBIT && cpu_address < 16'h0200;
    wire [16:0] effective_ram = {ram_address[16] && !aux_inhibit, ram_address[15:0]};
    wire firmware_test = cpu_address == 16'hE000 && !high_read;
    wire protected_write = firmware_test && cpu_write && !control[4] && !IGNORE_FW_PROTECT;
    wire language_access = cpu_address >= 16'hD000 && (cpu_write ? high_write : high_read);
    wire alternate_zp = card_mode[4] && !IGNORE_ZP_CONTEXT && effective_ram[16] &&
                        cpu_address == 16'h0000;
    wire unsupported_alternate_zp = card_mode[4] && effective_ram[16] &&
                                    cpu_address < 16'h0200 && cpu_address != 16'h0000;
    wire firmware_read = !IGNORE_FW_OVERLAY && nmi_overlay && !cpu_write &&
                         ((cpu_address >= 16'hD000 && cpu_address < 16'hD006) ||
                          (cpu_address == 16'hD006 && !cpu_sync));
    wire [17:0] physical = alternate_zp ? 18'h30000 :
        language_access && ALIAS_LC_BANKS && cpu_address == 16'hD000
        ? {1'b0, effective_ram[16], 4'hD, effective_ram[11:0]} : external_cx_read ? 18'h20000 + {2'b0, cpu_address} : receiver_read ? 18'h25000 + {2'b0, cpu_address} - 18'h0D000 :
        monitor_read && cpu_address >= 16'hFFFA ? 18'h27FFA + {2'b0, cpu_address} - 18'h0FFFA :
        monitor_read ? 18'h20000 + {2'b0, cpu_address} - 18'h0C000 : firmware_test ? 18'h26000 :
        firmware_read ? 18'h25000 + {2'b0, cpu_address} - 18'h0D000 :
        cpu_address >= 16'hFFFA
        ? (card_mode[3] ? 18'h2FFFA : 18'h23FFA) + {2'b0, cpu_address} - 18'h0FFFA : {1'b0, effective_ram};
    wire unsupported_cpu = unsupported_alternate_zp || (io_space && !allowed_io) ||
                           (!io_space && !external_cx_read && !cfff_read && !monitor_read && !receiver_read && !firmware_read && !firmware_test && !language_access && cpu_address >= 16'hC000 &&
                            (cpu_address < 16'hFFFA || cpu_write));
    wire runnable = (!runtime_paused || cpu_memory_wait) && cpu_valid && cpu_running && !start_pending && !boundary && !fault && !unsupported_cpu &&
                    (!reset_stopping || cpu_memory_wait);
    wire released = (!trap && !capture_valid) || permitted;
    // ACK after an address release waits for the CPU's next report capture.
    wire hold_ack = req_write && !req_word && (req_offset == 6'h0C || req_offset == 6'h19)
                    && cpu_running && !runtime_refresh && !capture_valid && !boundary && !fault;
    assign req_ready = host_ready && !hold_ack && !reset_stopping;
    assign rsp_error = host_error;
    assign boundary = 1'b0;
    assign master_valid[1] = runnable && released && !io_space && !protected_write && !cpu_memory_wait && !reset_stopping;
    assign master_write[1] = cpu_write;
    assign master_rsp_ready[1] = cpu_memory_wait && pace_due && runnable && released;
    assign cpu_ready = runnable && released && pace_due &&
                       (io_space ? allowed_io : (protected_write || (cpu_memory_wait && master_rsp_valid[1])));
    assign master_rsp_ready[0] = host_mem_rsp_ready;

    card_irq_host_registers host (
        .clk(clk), .reset(!por_n), .req_valid(req_valid && !hold_ack && !reset_stopping), .req_ready(host_ready),
        .req_offset(req_offset), .req_word(req_word), .req_write(req_write), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(host_error),
        .mem_req_valid(master_valid[0]), .mem_req_ready(master_ready[0]),
        .mem_req_addr(host_addr), .mem_req_write(master_write[0]),
        .mem_req_wdata(host_wdata), .mem_req_be(host_be),
        .mem_rsp_valid(master_rsp_valid[0]), .mem_rsp_ready(host_mem_rsp_ready),
        .mem_rsp_rdata(master_rdata), .mem_rsp_denied(denied), .control(control), .index(host_index),
        .capture_status(capture_valid ? capture_status : 8'b0),
        .capture_address(capture_valid ? capture_address : 16'b0), .capture_data(capture_data),
        .keyboard_status({keyboard[7], 7'b0}), .opaque08(display_switches),
        .sidefx_valid(sidefx_valid), .sidefx_offset(sidefx_offset), .sidefx_word(sidefx_word),
        .sidefx_write(sidefx_write), .sidefx_wdata(sidefx_wdata),
        .ack_write(ack), .read_release_write(read_release), .capture_address_read(address_read),
        .control_write(), .command_write(command_write), .mask_write(mask_write),
        .keyboard_write(keyboard_write)
    );
    card_irq_cpu_bus processor (
        .clk(clk), .reset(!por_n || !cpu_running), .sample_tick(pace_due), .ready(cpu_ready), .read_data(cpu_rdata),
        .irq_n(candidate_irq_n), .nmi_n(candidate_nmi_n), .valid(cpu_valid), .address(cpu_address),
        .ram_address(ram_address), .write(cpu_write), .write_data(cpu_wdata), .sync(cpu_sync),
        .vector_pull(vector_pull), .rti_done(rti_done), .halted(cpu_halted), .high_ram_read(high_read),
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

    wire opcode02_complete = cpu_ready && cpu_sync && !cpu_write &&
                             cpu_memory_wait && master_rsp_valid[1] && cpu_rdata == 8'h02;
    wire candidate_nmi_n = SUPPRESS_NMI ||
        !((nmi_pending && nmi_delay_left == 0) || (opcode02_complete && NMI_DELAY == 0));
    wire candidate_irq_n = SUPPRESS_IRQ || !(irq_level && irq_delay_left == 0);

    always @* begin
        cpu_rdata = physical[0] ? master_rdata[15:8] : master_rdata[7:0];
        case (cpu_address)
            16'hCFFF: if (cfff_read) cpu_rdata = FLOATING_DATA;
            16'hC07D: cpu_rdata = 8'hA5;
            16'hC0E8, 16'hC0E9, 16'hC0A0: cpu_rdata = 8'hA5;
            16'hC000: cpu_rdata = keyboard;
            16'hC010: cpu_rdata = {control[7], 7'b0};
            16'hC019: cpu_rdata = {control[6], 7'b0};
            16'hC015: cpu_rdata = {internal_rom, 7'b0};
            16'hC017: cpu_rdata = {slot3_rom, 7'b0};
            16'hC018: cpu_rdata = {mode_store80, 7'b0};
            16'hC01A: cpu_rdata = {mode_text, 7'b0};
            16'hC01B: cpu_rdata = {mode_mixed, 7'b0};
            16'hC01C: cpu_rdata = {mode_page2, 7'b0};
            16'hC01D: cpu_rdata = {mode_hires, 7'b0};
            16'hC01E: cpu_rdata = {mode_altchar, 7'b0};
            16'hC01F: cpu_rdata = {mode_col80, 7'b0};
            16'hC02B: cpu_rdata = card_mode;
            16'hC061: cpu_rdata = {GAME_INPUTS[0], 7'b0};
            16'hC062: cpu_rdata = {GAME_INPUTS[1], 7'b0};
            16'hC063: cpu_rdata = {GAME_INPUTS[2], 7'b0};
            16'hC078, 16'hC079, 16'hC07A, 16'hC07B, 16'hC07C:
                cpu_rdata = host_return;
            16'hC050, 16'hC051, 16'hC052, 16'hC053,
            16'hC054, 16'hC055, 16'hC056, 16'hC057,
            16'hC058, 16'hC059, 16'hC05A, 16'hC05B,
            16'hC05C, 16'hC05D, 16'hC05E, 16'hC05F: cpu_rdata = FLOATING_DATA;
            default: if (iwm_selected) cpu_rdata = iwm_rdata;
        endcase
    end

    always @(posedge clk) begin
        if (!por_n) begin
            host_return <= 0;
            nmi_pending <= 0;
            nmi_overlay <= 0;
            irq_level <= 0;
            nmi_delay_left <= 0;
            irq_delay_left <= 0;
            cpu_running <= 0;
            start_pending <= 0;
            reset_pending <= 0;
            reset_restart <= 0;
            internal_rom <= 0;
            card_mode <= 0;
            slot3_rom <= 0;
            internal_c8 <= 0;
            monitor_active <= 0;
            armed <= 0;
            runtime_paused <= 0;
            runtime_refresh <= 0;
            report_mode <= 0;
            reset_mask <= 0;
            keyboard <= 0;
            display_switches <= 0;
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
            permitted <= 0;
            cpu_memory_wait <= 0;
            cpu_completed <= 0;
            fault <= 0;
            start_mask <= 0;
            start_override <= 0;
            start_count <= 0;
            first_fault <= 0;
            command_context <= 0;
        end else begin
            if (nmi_delay_left != 0) nmi_delay_left <= nmi_delay_left - 1;
            if (irq_delay_left != 0) irq_delay_left <= irq_delay_left - 1;
            if (opcode02_complete) begin
                nmi_pending <= 1;
                nmi_delay_left <= NMI_DELAY;
            end
            if (cpu_ready && vector_pull && cpu_address == 16'hFFFA) begin
                nmi_pending <= 0;
                nmi_overlay <= 1;
            end
            if (cpu_ready && rti_done) nmi_overlay <= 0;
            if (master_valid[1] && master_ready[1]) cpu_memory_wait <= 1;
            if (master_rsp_valid[1] && master_rsp_ready[1]) begin
                cpu_memory_wait <= 0;
                if (denied) begin
                    fault <= 1;
                    if (!fault) first_fault <= 1;
                end
            end
            if (start_pending && drained && !cpu_memory_wait && !reset_stopping) begin
                cpu_running <= 1;
                start_pending <= 0;
            end
            if (cpu_running && !start_pending && !boundary &&
                (cpu_halted || (cpu_valid && unsupported_cpu))) begin
                fault <= 1;
                if (!fault) first_fault <= cpu_halted ? 4'd2 : 4'd3;
            end
            if (runnable && trap && !permitted && !capture_valid) begin
                capture_valid <= 1;
                capture_count <= capture_count + 1;
                capture_address <= cpu_address;
                capture_data <= cpu_write ? cpu_wdata : 0;
                // Host status includes the held access before its ACK.
                if (display_switch && !IGNORE_SOFTSWITCH) begin
                    case (cpu_address)
                        16'hC00F, 16'hC00E:
                            if (!SOFTSWITCH_STUCK_MASK[0]) display_switches[0] <= cpu_address[0];
                        16'hC051, 16'hC050:
                            if (!SOFTSWITCH_STUCK_MASK[1]) display_switches[1] <= cpu_address[0];
                        16'hC057, 16'hC056:
                            if (!SOFTSWITCH_STUCK_MASK[2]) display_switches[2] <= cpu_address[0];
                        16'hC05F, 16'hC05E:
                            if (!SOFTSWITCH_STUCK_MASK[3]) display_switches[3] <= cpu_address[0];
                        16'hC00D, 16'hC00C:
                            if (!SOFTSWITCH_STUCK_MASK[4]) display_switches[4] <= cpu_address[0];
                        16'hC053, 16'hC052:
                            if (!SOFTSWITCH_STUCK_MASK[5]) display_switches[5] <= cpu_address[0];
                        16'hC055, 16'hC054:
                            if (!SOFTSWITCH_STUCK_MASK[6]) display_switches[6] <= cpu_address[0];
                        16'hC001, 16'hC000:
                            if (!SOFTSWITCH_STUCK_MASK[7]) display_switches[7] <= cpu_address[0];
                        default: ;
                    endcase
                end
                capture_reset <= reset_vector;
                capture_display <= is_display;
                capture_read_release <= (service_register || cpu_address == 16'hC07D) && !cpu_write;
                capture_address_release <= is_display && report_mode;
                capture_write <= cpu_write;
                if (reset_vector) capture_status <= 8'h80;
                else if (display_switch) capture_status <= monitor_active ? 8'hE0 : 8'h08;
                else if (service_register || cpu_address == 16'hC07D) capture_status <= cpu_write ? 8'hE0 : 8'hE1;
                else if (cpu_address == 16'hC0E9) capture_status <= 8'h38;
                else if (cpu_address == 16'hC0E8) capture_status <= 8'h28;
                else if (cpu_address == 16'hC0A0) capture_status <= cpu_write ? 8'h08 : 8'h09;
                else begin
                    case (cpu_address & 16'hFC00)
                        16'h0400: capture_status <= (monitor_active ? 8'h42 : 8'h02) | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        16'h0800: capture_status <= (monitor_active ? 8'h62 : 8'h22) | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        16'h2000: capture_status <= 8'h04 | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        16'h4000: capture_status <= 8'h24 | (ram_address[16] ? 8'h08 : 0) | {7'b0, report_mode};
                        default: begin
                            fault <= 1;
                            if (!fault) first_fault <= 4;
                        end
                    endcase
                end
            end
            if (cpu_ready) begin
                cpu_completed <= cpu_completed + 1;
                if (cpu_address[15:8] == 8'hC3 && !slot3_rom) internal_c8 <= 1;
                else if (cpu_address == 16'hCFFF) internal_c8 <= 0;
                if (cpu_write && cpu_address == 16'hC007) internal_rom <= 1;
                if (cpu_write && cpu_address == 16'hC006) internal_rom <= 0;
                if (cpu_write && cpu_address == 16'hC00A) slot3_rom <= 0;
                if (cpu_write && cpu_address == 16'hC00B) slot3_rom <= 1;
                if (cpu_write && cpu_address == 16'hC02B) card_mode <= cpu_wdata;
                if (cpu_write && cpu_address == 16'hC028 && cpu_wdata[7] && !IGNORE_FW_OVERLAY)
                    card_mode[3] <= 1;
                
                permitted <= 0;
                if (cpu_address == 16'hC010 && (monitor_active || !cpu_write)) keyboard[7] <= 0;
            end
            if (read_release && capture_valid && capture_read_release)
                host_return <= sidefx_wdata[7:0];
            if (mask_write) reset_mask <= sidefx_wdata[7:0];
            if (keyboard_write) keyboard <= {monitor_active || sidefx_wdata[7], sidefx_wdata[6:0]};
            if (command_write) begin
                if (!fault) command_context <= {sidefx_wdata, reset_mask,
                    runtime_mode, monitor_active, cpu_running, reset_pending,
                    armed, capture_valid, capture_reset, start_pending,
                    capture_address, capture_status};
                if (reset_command) begin
                    reset_pending <= 1;
                    reset_restart <= !sidefx_word;
                end else if (!sidefx_word && sidefx_wdata[7:0] == 8'h80 && armed && reset_mask != 8'hFC) begin
                    runtime_paused <= 1;
                    runtime_refresh <= 1;
                end else if (!sidefx_word && (sidefx_wdata[7:0] & 8'hDF) == 8'h88) begin
                    if ((capture_valid && capture_reset) || armed) begin
                        armed <= 1;
                        runtime_paused <= 0;
                        report_mode <= 0;
                        irq_level <= sidefx_wdata[5];
                        if (sidefx_wdata[5] && !irq_level) irq_delay_left <= IRQ_DELAY;
                    end else begin
                        fault <= 1;
                        if (!fault) first_fault <= 5;
                    end
                end else if (!sidefx_word && sidefx_wdata[7:0] == 8'h98 && armed)
                    report_mode <= 1;
                else begin
                    fault <= 1;
                    if (!fault) first_fault <= 6;
                end
            end
            if (ack || read_release || (address_read && capture_valid && capture_address_release)) begin
                if (capture_valid) begin
                    if (sidefx_write && !read_release && sidefx_wdata[7:0] != 0) begin
                        fault <= 1;
                        if (!fault) first_fault <= 7;
                    end
                    else if ((read_release != capture_read_release && !address_read) ||
                             (capture_reset && !armed)) begin
                        fault <= 1;
                        if (!fault) first_fault <= 8;
                    end
                    else begin
                        capture_valid <= 0;
                        permitted <= 1;
                    end
                end else if (ack && runtime_refresh) runtime_refresh <= 0;
                else if (cpu_running && (ack || read_release)) begin
                    fault <= 1;
                    if (!fault) first_fault <= 9;
                end
            end
            // Accepted memory work completes before CPU and capture state reset.
            if (reset_commit) begin
                host_return <= 0;
                reset_pending <= 0;
                internal_rom <= 0;
                card_mode <= 0;
                slot3_rom <= 0;
                internal_c8 <= 0;
                if (reset_restart) begin
                    monitor_active <= runtime_mode || (reset_mask & 8'hFC) == 8'h20;
                    if (!fault) begin
                        start_mask <= reset_mask;
                        start_override <= runtime_mode;
                        if (start_count != 7) start_count <= start_count + 3'd1;
                    end
                end
                nmi_pending <= 0;
                nmi_overlay <= 0;
                irq_level <= 0;
                nmi_delay_left <= 0;
                irq_delay_left <= 0;
                cpu_running <= 0;
                start_pending <= reset_restart;
                armed <= 0;
                runtime_paused <= 0;
                runtime_refresh <= 0;
                report_mode <= 0;
                capture_valid <= 0;
                permitted <= 0;
                keyboard <= 0;
                display_switches <= 0;
            end
        end
    end
endmodule
