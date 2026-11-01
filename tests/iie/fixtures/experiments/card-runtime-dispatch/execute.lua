local run = assert(os.getenv('IIE_DISPATCH_RUN'))
local code = assert(os.getenv('IIE_DISPATCH_CODE'))
local service = tonumber(os.getenv('IIE_DISPATCH_SERVICE') or '1')
local frames, ack = 0, false
local base, world, card = 0x200000, 0x300000, 0xe00000
local taps = {}
local bus = assert(io.open(run .. '/bus.jsonl', 'w'))

emu.register_frame_done(function()
    frames = frames + 1
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    if frames == 3000 then
        space:read_u32(0x00a00000)
        local file = assert(io.open(code, 'rb'))
        local bytes = file:read('a')
        file:close()
        for i = 1, #bytes do space:write_u8(base + i - 1, bytes:byte(i)) end
        local loaded = assert(io.open(run .. '/loaded.bin', 'wb'))
        loaded:write(space:read_range(base, base + #bytes - 1, 8))
        loaded:close()
        for i = world - 0x5960, world + 0x2e8 do space:write_u8(i, 0) end
        space:write_u32(world - 0x1236, card)
        space:write_u8(0x260, 0)
        assert(space:read_u16(base + 0x281c) == 0x286d, 'RAM injection failed')
        taps[#taps + 1] = space:install_read_tap(card, card + 0x23, 'dispatch-read', function(offset, data, mask)
            local first, count = nil, 0
            for lane = 0, 3 do
                if ((mask >> ((3 - lane) * 8)) & 0xff) ~= 0 then
                    first = first or lane
                    count = count + 1
                end
            end
            local off, result = offset - card + first, 0
            if off == 1 and count == 1 then result = ack and 0 or 0xe0
            elseif off == 4 and count == 2 then result = 0xc07d
            elseif off == 0xc and count == 1 then result = service
            else error(string.format('Unexpected read %x/%d', off, count)) end
            bus:write(string.format('[false,%d,%d,%d]\n', count * 8, off, result))
            return (data & ~mask) | ((result << ((4 - first - count) * 8)) & mask)
        end)
        taps[#taps + 1] = space:install_write_tap(card, card + 0x23, 'dispatch-write', function(offset, data, mask)
            assert(offset - card == 0xc and mask == 0xff000000 and (data >> 24) == 0, 'Unexpected write')
            assert(not ack, 'Duplicate ACK')
            ack = true
            bus:write('[true,8,12,0]\n')
        end)
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu')
        cpu.state['SR'].value = 0x2700
        cpu.state['A5'].value = world
        cpu.state['A7'].value = 0x3f0000
        cpu.state['PC'].value = base + 0x281c
    elseif frames == 3001 then
        machine.debugger:command('trace off,:maincpu')
        bus:close()
        local file = assert(io.open(run .. '/state.txt', 'w'))
        file:write(string.format('ack=%s service=%d pc=%x sp=%x\n', tostring(ack),
            space:read_u8(world - 0x88f), cpu.state['PC'].value, cpu.state['A7'].value))
        file:close()
        machine:exit()
    end
end)



