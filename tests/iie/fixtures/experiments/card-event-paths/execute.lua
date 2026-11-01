local run = assert(os.getenv('IIE_EVENT_RUN'))
local code = assert(os.getenv('IIE_EVENT_CODE'))
local fault = os.getenv('IIE_EVENT_FAULT') == '1'
local event_type = assert(tonumber(os.getenv('IIE_EVENT_TYPE')))
assert(event_type == 1 or event_type == 2 or event_type == 11)
local frames = 0

emu.register_frame_done(function()
    frames = frames + 1
    if frames ~= 3000 then return end
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    space:read_u32(0xa00000)
    local input = assert(io.open(code, 'rb'))
    local bytes = input:read('a')
    input:close()
    for i = 1, #bytes do space:write_u8(0x200000 + i - 1, bytes:byte(i)) end
    for i = 0x2fa6a0, 0x3002e8 do space:write_u8(i, 0) end
    space:write_u32(0x2fedca, 0xe00000)
    space:write_u8(0x15d, 0x80)
    space:write_u16(0x8d0, 0x8000)
    for address = 0x174, 0x180, 4 do space:write_u32(address, 0) end
    for address = 0x320000, 0x3202ff do space:write_u8(address, 0) end
    for slot = 0, 23 do
        space:write_u16(0x300000 - 0x1396 + slot * 2, 0)
    end
    space:write_u16(0x300000 - 0x1396 + 2, 1 << ((event_type + 1) % 16))
    for index, slot in ipairs({20, 7, 0}) do
        local handler = 0x320000 + (index - 1) * 0x100
        space:write_u16(0x300000 - 0x1396 + slot * 2, 1 << event_type)
        space:write_u32(0x300000 - 0x13ea + slot * 4, handler)
        space:write_u32(0x300000 - 0x140a + slot * 4, 0x330000 + slot * 0x100)
        space:write_u16(handler + 0x1c, 0x70ff)
        space:write_u16(handler + 0x1e, 0x76ff)
        space:write_u16(handler + 0x20, 0x4e75)
        cpu.debug:bpset(handler + 0x1c, '1',
            'd@310100=d0; d@310104=d1; d@310108=d3; d@31010c=a0; '
            .. 'd@310110=a1; d@310114=a3; d@310118=a7; '
            .. 'save "' .. run .. '/handler-' .. slot .. '.bin",310100,1c; g')
    end
    space:write_u32(0x3f0000, 0x280000)
    local writes = assert(io.open(run .. '/writes.txt', 'w'))
    _G.event_tap = space:install_write_tap(0xe00000, 0xe00023, 'event-write', function(offset, data, mask)
        writes:write(string.format('%08x %08x %08x\n', offset, data, mask))
        writes:flush()
    end)
    machine.debugger:command('focus :maincpu')
    machine.debugger.visible_cpu = cpu
    cpu.debug:bpset(0x20250c, '1',
        'd@310000=d0; d@310004=a0; save "' .. run .. '/trap.bin",310000,8; '
        .. 'w@(a5-8e0)=' .. string.format('%x', event_type) .. '; d@(a5-8de)=ff41; d@(a5-8da)=12345678; '
        .. 'd@(a5-8d6)=00020003; w@(a5-8d2)=0; d0=0; pc=20250e; g')
    if fault then
        cpu.debug:bpset(0x2025d8, 'd3==7', 'pc=2025dc; g')
    end
    cpu.debug:bpset(0x280000, '1',
        'save "' .. run .. '/world.bin",2fa6a0,5c49; '
        .. 'save "' .. run .. '/handlers.bin",320000,300; '
        .. 'save "' .. run .. '/code.bin",200000,' .. string.format('%x', #bytes) .. '; '
        .. 'd@310000=pc; d@310004=a7; d@310008=d0; d@31000c=a5; '
        .. 'save "' .. run .. '/state.bin",310000,10; trace off,:maincpu; quit')
    machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
    cpu.state['SR'].value = 0x2700
    cpu.state['A5'].value = 0x300000
    cpu.state['A7'].value = 0x3f0000
    cpu.state['PC'].value = 0x2024aa
end)
