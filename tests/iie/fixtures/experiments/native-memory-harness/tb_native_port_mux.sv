`timescale 1ns/1ps
module tb_native_port_mux;
    reg clk = 0;
    always #5 clk = !clk;
    reg por_n = 0, reset_request = 0;
    wire drained;
    reg [1:0] client_req = 0, client_we = 0;
    reg [23:0] card_addr = 0, floppy_addr = 0;
    reg [15:0] card_din = 0, floppy_din = 0;
    wire [1:0] client_ack;
    wire [15:0] card_dout, floppy_dout;
    wire native_req, native_we, native_ack;
    wire [23:0] native_addr;
    wire [15:0] native_din;
    reg [15:0] native_dout = 0;
    reg backend_ack = 0, stale_ack = 0;
    assign native_ack = backend_ack || stale_ack;

    card_native_port_mux mux (
        .clk(clk), .por_n(por_n), .reset_request(reset_request), .drained(drained),
        .client_req(client_req), .client_we(client_we),
        .card_addr(card_addr), .floppy_addr(floppy_addr),
        .card_din(card_din), .floppy_din(floppy_din), .client_ack(client_ack),
        .card_dout(card_dout), .floppy_dout(floppy_dout),
        .native_req(native_req), .native_we(native_we), .native_addr(native_addr),
        .native_din(native_din), .native_ack(native_ack), .native_dout(native_dout)
    );

    reg busy = 0, operation_write = 0;
    integer age = 0, low_age = 0;
    integer native_starts = 0, native_commits = 0, early_write_acks = 0;
    integer read_acks = 0, rearmed = 0;
    reg [40:0] frozen;
    always @(posedge clk) begin
        if (por_n) begin
            if (!busy && native_req) begin
                if (native_ack) $fatal(1, "new native request with stale ACK");
                busy <= 1;
                operation_write <= native_we;
                frozen <= {native_we, native_addr, native_din};
                native_dout <= native_addr[15:0] ^ 16'ha55a;
                age <= 0;
                low_age <= 0;
                native_starts = native_starts + 1;
            end else if (busy) begin
                if ({native_we, native_addr, native_din} !== frozen)
                    $fatal(1, "native fields changed before ACK rearm");
                age <= age + 1;
                if (operation_write && age == 1) begin
                    backend_ack <= 1;
                    early_write_acks = early_write_acks + 1;
                end
                if (operation_write && age == 4) native_commits = native_commits + 1;
                if (!operation_write && age == 4) begin
                    backend_ack <= 1;
                    read_acks = read_acks + 1;
                end
                if (backend_ack && !native_req) begin
                    low_age <= low_age + 1;
                    if (low_age == 3) begin
                        backend_ack <= 0;
                        busy <= 0;
                        rearmed = rearmed + 1;
                    end
                end
            end
        end
    end

    integer ticks = 0, completed0 = 0, completed1 = 0;
    integer grants0 = 0, grants1 = 0, contested = 0;
    reg expected_next = 0, previous_owned = 0, previous_stop = 0;
    reg [1:0] previous_req = 0;
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (ticks > 3000) $fatal(1, "watchdog");
        if (por_n) begin
            if (client_ack == 3) $fatal(1, "ACK leaked to both clients");
            if (mux.state != 0 && !previous_owned) begin
                if (previous_stop) $fatal(1, "ownership granted while stopped");
                if (previous_req == 3) begin
                    contested = contested + 1;
                    if (mux.owner != expected_next) $fatal(1, "round robin mismatch");
                end
                expected_next = !mux.owner;
                if (mux.owner) grants1 = grants1 + 1;
                else grants0 = grants0 + 1;
            end
            if (mux.state != 0) begin
                if (mux.owner && (client_ack[0] || card_dout != 0))
                    $fatal(1, "floppy data/ACK leaked to card");
                if (!mux.owner && (client_ack[1] || floppy_dout != 0))
                    $fatal(1, "card data/ACK leaked to floppy");
            end else if (client_ack != 0 || card_dout != 0 || floppy_dout != 0)
                $fatal(1, "unowned response leaked");
            previous_owned = mux.state != 0;
            previous_stop = reset_request;
            previous_req = client_req;
        end
    end

    task automatic transaction(input bit owner, input bit write_op, input [23:0] address,
                     input integer hold_ticks);
        integer starts_at_ack;
        begin
            @(negedge clk);
            if (owner) begin floppy_addr = address; floppy_din = 16'hb123; end
            else begin card_addr = address; card_din = 16'hc456; end
            client_we[owner] = write_op;
            client_req[owner] = 1;
            wait(client_ack[owner]);
            @(negedge clk);
            if ((owner ? floppy_dout : card_dout) !== (address[15:0] ^ 16'ha55a))
                $fatal(1, "private read data mismatch");
            starts_at_ack = native_starts;
            // Posted-ACK input changes must not alter the frozen native bundle.
            if (owner) begin floppy_addr = ~address; floppy_din = 16'hffff; end
            else begin card_addr = ~address; card_din = 16'hffff; end
            repeat (hold_ticks) begin
                @(negedge clk);
                if (!native_req || !client_ack[owner] || native_starts != starts_at_ack)
                    $fatal(1, "held request regranted or ACK lost");
            end
            client_req[owner] = 0;
            wait(!client_ack[owner]);
            if (owner) completed1 = completed1 + 1;
            else completed0 = completed0 + 1;
        end
    endtask

    integer card_iteration, floppy_iteration, stop_snapshot;
    initial begin
        repeat (3) @(negedge clk);
        por_n = 1;
        stale_ack = 1;
        fork
            transaction(0, 0, 24'h540012, 3);
            begin
                repeat (8) begin
                    @(negedge clk);
                    if (native_req || client_ack != 0 || drained) $fatal(1, "stale ACK accepted");
                end
                stale_ack = 0;
            end
        join
        wait(drained);

        fork
            begin
                for (card_iteration = 0; card_iteration < 12; card_iteration = card_iteration + 1)
                    transaction(0, card_iteration[0], 24'h540100 + 24'(card_iteration), 8);
            end
            begin
                for (floppy_iteration = 0; floppy_iteration < 12; floppy_iteration = floppy_iteration + 1)
                    transaction(1, 0, 24'h600200 + 24'(floppy_iteration), 2);
            end
        join
        wait(drained);
        if (grants0 != 13 || grants1 != 12 || contested < 10)
            $fatal(1, "contention coverage or fairness failed: %0d %0d contested=%0d", grants0, grants1, contested);

        fork
            transaction(0, 1, 24'h540300, 8);
            begin
                wait(native_req);
                @(negedge clk);
                reset_request = 1;
                floppy_addr = 24'h600400;
                floppy_din = 0;
                client_req[1] = 1;
            end
        join
        wait(drained);
        stop_snapshot = native_starts;
        repeat (10) begin
            @(negedge clk);
            if (native_req || native_starts != stop_snapshot || client_ack != 0)
                $fatal(1, "queued client bypassed quiesce");
        end
        reset_request = 0;
        wait(client_ack[1]);
        @(negedge clk);
        if (floppy_dout !== (16'h0400 ^ 16'ha55a)) $fatal(1, "queued floppy data mismatch");
        client_req[1] = 0;
        wait(!client_ack[1]);
        completed1 = completed1 + 1;
        wait(drained);
        @(negedge clk);
        if (native_starts != completed0 + completed1 || rearmed != native_starts)
            $fatal(1, "missing or duplicate native operation");
        if (native_commits != early_write_acks || native_commits != 7 || read_acks != 20)
            $fatal(1, "write/read coverage mismatch");
        $display("PASS native-port-mux starts=%0d rearmed=%0d card=%0d floppy=%0d contested=%0d writes=%0d reads=%0d ticks=%0d", native_starts, rearmed, completed0, completed1, contested, native_commits, read_acks, ticks);
        $finish;
    end
endmodule
