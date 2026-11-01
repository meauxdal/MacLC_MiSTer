local frames = 0
local run = assert(os.getenv('IIE_SLOT_RUN'), 'IIE_SLOT_RUN is required')
emu.register_frame_done(function()
    frames = frames + 1
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    if frames == 1 then
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        print(string.format('ARM pc=%08x root=%08x', cpu.state['PC'].value, space:read_u32(0xd24)))
        cpu.debug:bpset(0xa060a0, '1',
            'printf "SRT_START frame=%d pc=%08X a0=%08X",frame,pc,a0; trace ' .. run .. '/build.txt,:maincpu; g')
        cpu.debug:bpset(0xa060b2, '1',
            'printf "SRT_ROOT frame=%d root=%08X",frame,a1; g')
        cpu.debug:bpset(0xa0617e, '1',
            'printf "SRT_BUILD frame=%d pc=%08X d0=%08X record=%08X key=%08X type_hi=%08X type_lo=%08X source=%08X flags=%02X",frame,pc,d0,a1,d@a1,d@(a1+8),d@(a1+c),d@(a1+10),b@(a1+17); g')
        cpu.debug:bpset(0xa060ea, '1',
            'printf "SRT_END frame=%d root=%08X",frame,d@d24; trace off,:maincpu; g')
        cpu.debug:bpset(0xa06726, '1',
            'printf "SRT_DELETE frame=%d record=%08X key=%08X type_hi=%08X type_lo=%08X",frame,a1,d@a1,d@(a1+8),d@(a1+c); g')
        cpu.debug:bpset(0xa4b974, '1',
            'printf "PRIMARY_ENTER frame=%d pc=%08X",frame,pc; trace ' .. run .. '/primary.txt,:maincpu; g')
        cpu.debug:bpset(0xa4bbc2, '1',
            'printf "PRIMARY_END frame=%d pc=%08X",frame,pc; trace off,:maincpu; g')
        for _, site in ipairs({0xa4b9ea, 0xa4bca2, 0xa4bcce, 0xa4bcd4, 0xa4bcee,
                               0xa4beb0, 0xa4beda, 0xa4bede, 0xa4bee4, 0xa4bee8,
                               0xa4bf04, 0xa4bf08, 0xa4bf0e}) do
            cpu.debug:bpset(site, '1',
                'printf "PROBE frame=%d pc=%08X d0=%08X d1=%08X d2=%08X a3=%08X sr=%04X mmu=%02X vector8=%08X",frame,pc,d0,d1,d2,a3,sr,b@cb2,d@8; g')
        end
        for _, address in ipairs({0x80000010, 0x8000001c}) do
            cpu.debug:wpset(space, 'r', address, 2, '1',
                'printf "PROBE_BUS frame=%d pc=%08X address=%08X size=%d data=%08X",frame,pc,wpaddr,wpsize,wpdata; g')
        end
    end
    if frames == 1000 then
        for _, line in ipairs(machine.debugger.consolelog) do print('DBG ' .. line) end
        local file = assert(io.open(run .. '/ram.bin', 'wb'))
        file:write(space:read_range(0, 0x3fffff, 8))
        file:close()
    end
end)
