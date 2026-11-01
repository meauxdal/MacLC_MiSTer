    task pause_pending(input reg writing);
        integer completed_before, requests_before, responses_before, stores_after;
        begin
            if (writing) begin
                wait(dut.platform.card.card.master_valid[1] &&
                     dut.platform.card.card.master_write[1]);
                @(negedge clk_sys);
            end
            force dut.platform.card.card.pace_due = 0;
            wait(dut.platform.card.card.cpu_memory_wait);
            @(negedge clk_sys);
            if (dut.platform.card.card.cpu_write != writing || capture_valid)
                $fatal(1, "pause probe selected wrong work");
            completed_before = int'(cpu_completed);
            requests_before = cpu_requests;
            responses_before = cpu_responses;
            transact(1, 0, 32, 128, 0);
            if (!dut.platform.card.card.runtime_paused ||
                !dut.platform.card.card.cpu_memory_wait ||
                cpu_completed != 32'(completed_before))
                $fatal(1, "pause lost outstanding work");
            release dut.platform.card.card.pace_due;
            repeat (256) @(negedge clk_sys);
            if (dut.platform.card.card.cpu_memory_wait)
                $fatal(1, "runtime hold blocked pending response");
            wait(dut.platform.card.card.drained);
            @(negedge clk_sys);
            stores_after = stores;
            repeat (32) @(negedge clk_sys);
            if (cpu_completed != 32'(completed_before + 1) ||
                cpu_requests != requests_before || cpu_responses != responses_before + 1 ||
                stores != stores_after || capture_valid || dut.platform.card.card.reset_pending)
                $fatal(1, "runtime hold did not drain exactly once");
            transact(1, 0, 32, 136, 0);
            transact(1, 0, 12, 0, 0);
            if (dut.platform.card.card.runtime_paused || dut.platform.card.card.runtime_refresh)
                $fatal(1, "runtime resume failed");
            $display("PAUSE_PENDING write=%0d completed=%0d requests=%0d responses=%0d",
                     writing, cpu_completed, cpu_requests, cpu_responses);
        end
    endtask
