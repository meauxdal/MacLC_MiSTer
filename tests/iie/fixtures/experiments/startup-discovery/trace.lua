local frames = 0
local run = assert(os.getenv('IIE_DISCOVERY_RUN'), 'IIE_DISCOVERY_RUN is required')

local function pb(label)
    local format, values = '', ''
    for offset = 0, 52, 4 do
        format = format .. '%08X'
        values = values .. string.format(',d@(temp0+%x)', offset)
    end
    return 'printf "' .. label .. ' pb=' .. format .. '"' .. values
end

local function breakpoint(address, action)
    return 'bpset ' .. address .. ',1,{' .. action .. '; g}'
end

emu.register_frame_done(function()
    frames = frames + 1
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    if frames == 3000 then
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        local handler = space:read_u32(0x5b8)
        print(string.format('ARM frame=%d handler=%08x', frames, handler))
        local after = 'printf "SLOT_RETURN pc=%08X d0=%08X a0=%08X",pc,d0,a0; '
            .. pb('POST')
        local result = 'printf "DISCOVERY_RETURN pc=%08X d0=%08X a5=%08X",pc,d0,a5'
        local absent = 'printf "ABSENT_DIALOG pc=%08X message=%08X base=%08X",pc,d1,d@(temp2-11e2); '
            .. 'trace off,:maincpu'
        local conf = 'printf "CONF_CALL pc=%08X base=%08X",pc,d@(temp2-11e2)'
        local candidate = 'printf "SRT_CANDIDATE record=%08X key=%08X type_hi=%08X type_lo=%08X",a1,d@a1,d@(a1+8),d@(a1+c)'
        local action = 'temp0=a0; temp1=d@(a6+4)-780; temp2=a5; '
            .. 'printf "SLOT_ENTER frame=%d pc=%08X d0=%08X a0=%08X a5=%08X a6=%08X code2=%08X mach=%04X processor=%04X",frame,pc,d0,a0,a5,a6,temp1,w@(a5-13be),w@(a5-1024); '
            .. pb('PRE') .. '; '
            .. breakpoint('temp1+99a', after) .. '; '
            .. breakpoint('temp1+780', result) .. '; '
            .. breakpoint('temp1+790', absent) .. '; '
            .. breakpoint('temp1+7dc', conf) .. '; '
            .. breakpoint('a065ca', candidate) .. '; '
            .. 'trace ' .. run .. '/instructions.txt,:maincpu; g'
        cpu.debug:bpset(handler,
            '(d0 & ffff)==15 && a0==a6-42 && w@(d@(a6+4)+218)==a06e', action)
        for _, address in ipairs({0xfee00000, 0x50fc0000, 0xe00000, 0xfc0000}) do
            local id = cpu.debug:wpset(space, 'rw', address, 0x100, '1',
                'printf "CANDIDATE_ACCESS frame=%d pc=%08X address=%08X size=%d data=%08X",frame,pc,wpaddr,wpsize,wpdata; g')
            print(string.format('WATCH id=%d start=%08x end=%08x', id, address, address + 0xff))
        end
    end
    if frames == 3600 then
        print('INPUT Return for observed Network Extension modal')
        machine.natkeyboard:post_coded('{ENTER}')
    end
    if frames == 4800 then
        for _, line in ipairs(machine.debugger.consolelog) do print('DBG ' .. line) end
        local count = space:read_u8(0x910)
        local name = count < 32 and space:read_range(0x911, 0x910 + count, 8) or ''
        print(string.format('FINAL CurApName=%q', name))
        for _, screen in pairs(machine.screens) do screen:snapshot('discovery.png') end
        local file = assert(io.open(run .. '/ram.bin', 'wb'))
        file:write(space:read_range(0, 0x3fffff, 8))
        file:close()
    end
end)


