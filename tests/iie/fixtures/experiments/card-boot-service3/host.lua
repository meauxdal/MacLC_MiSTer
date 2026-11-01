local run = assert(os.getenv('IIE_DISPATCH_RUN'))
local code = assert(os.getenv('IIE_DISPATCH_CODE'))
local frame_size = tonumber(assert(os.getenv('IIE_FRAME_SIZE')))
local profile = assert(os.getenv('IIE_BOOT_PROFILE'))
local flag, config
if profile == 'slot6' then flag, config = 0, 0xa5b6
elseif profile == 'slot8' then flag, config = 0, 0xa5b1
elseif profile == 'override' then flag, config = 0xa5, 0xa5b1
else error('Unknown boot profile') end
local base, world, card = 0x200000, 0x300000, 0xe00000
local frames, sequence, service_acks, return_writes = 0, 0, 0, 0
local taps = {}
local bus = assert(io.open(run .. '/bus.jsonl', 'w'))
bus:setvbuf('no')
local registers = assert(io.open(run .. '/registers.jsonl', 'w'))
registers:setvbuf('no')

local function bridge(write, width, offset, value)
    sequence = sequence + 1
    assert(sequence <= 512, 'Saved-register transaction bound')
    local name = run .. '/request-' .. sequence .. '.txt'
    local file = assert(io.open(name .. '.tmp', 'w'))
    file:write(string.format('%d %d %d %d %d\n', sequence, write and 1 or 0, width, offset, value))
    file:close()
    assert(os.rename(name .. '.tmp', name))
    local deadline = os.time() + 15
    repeat
        file = io.open(run .. '/response-' .. sequence .. '.txt', 'r')
        if file then
            local response = file:read('a')
            file:close()
            return assert(tonumber(response:match('^OK (%d+)')), response)
        end
    until os.time() >= deadline
    error('RTL bridge response deadline')
end

local function lanes(mask)
    local first, count = nil, 0
    for lane = 0, 3 do
        if ((mask >> ((3 - lane) * 8)) & 0xff) ~= 0 then
            first = first or lane
            count = count + 1
        end
    end
    assert(first ~= nil and (count == 1 or count == 2), 'Unexpected PDS width')
    return first, count
end

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
        local function overlay(path, address)
            local input = assert(io.open(path, 'rb'))
            local contents = input:read('a')
            input:close()
            for i = 1, #contents do space:write_u8(address + i - 1, contents:byte(i)) end
        end
        local function snapshot(name, address, size)
            local output = assert(io.open(run .. '/' .. name, 'wb'))
            output:write(space:read_range(address, address + size - 1, 8))
            output:close()
        end
        for i = 1, #bytes do space:write_u8(base + i - 1, bytes:byte(i)) end
        snapshot('loaded.bin', base, #bytes)
        for i = world - 0x5960, world + 0x2e8 do space:write_u8(i, 0) end
        overlay(assert(os.getenv('IIE_INIT_WORLD')), world - 0x5960)
        overlay(assert(os.getenv('IIE_INIT_CODE')), base)
        file = assert(io.open(assert(os.getenv('IIE_SWITCH_WORLD')), 'rb'))
        file:seek('set', 0x5960 - 0x972)
        assert(file:read(2) == string.char(0, 0), 'Expected completed reset-switch mode')
        file:close()
        space:write_u8(world - 0x5814, flag)
        space:write_u16(world - 0x86c, config)
        local fixture = assert(io.open(run .. '/boot-profile.bin', 'wb'))
        fixture:write(string.char(space:read_u8(world - 0x5814),
            (space:read_u16(world - 0x86c) >> 8) & 0xff,
            space:read_u16(world - 0x86c) & 0xff))
        fixture:close()
        space:write_u16(world - 0x972, 0)
        for i = 0x100000 - 64, 0x100000 + frame_size + 63 do space:write_u8(i, 0x5a) end
        space:write_u32(world - 0x1236, card)
        space:write_u8(0x260, 0)
        space:write_u16(world - 0x97c, 0x5a5a)
        assert(space:read_u16(base + 0x281c) == 0x286d, 'RAM injection failed')
        local function record(write, width, offset, value)
            bus:write(string.format('[%s,%d,%d,%d]\n', write and 'true' or 'false', width, offset, value))
            if write and (offset == 0xc or offset == 0x19) then
                registers:write(string.format('[%d,%d,%d,%d,%d,%d,%d,%d,%d]\n', sequence,
                    cpu.state['PC'].value, offset, value,
                    space:read_u8(world - 0x894), space:read_u8(world - 0x893),
                    space:read_u8(world - 0x892), space:read_u8(world - 0x891),
                    space:read_u8(world - 0x890)))
            end
        end
        taps[#taps + 1] = space:install_read_tap(card, card + 0x23, 'saved-read', function(offset, data, mask)
            local first, count = lanes(mask)
            local off = offset - card + first
            if return_writes == 20 then
                assert(off == 1 and count == 1, 'Unexpected post-boundary PDS read')
                return data & ~mask
            end
            local result = bridge(false, count * 8, off, 0)
            record(false, count * 8, off, result)
            return (data & ~mask) | ((result << ((4 - first - count) * 8)) & mask)
        end)
        taps[#taps + 1] = space:install_write_tap(card, card + 0x23, 'saved-write', function(offset, data, mask)
            local first, count = lanes(mask)
            local off = offset - card + first
            local value = (data >> ((4 - first - count) * 8)) & ((1 << (count * 8)) - 1)
            assert(count == 1 and (off == 0xc or off == 0x19 or off == 0x21), 'Unexpected PDS write')
            if off == 0xc then
                assert(value == 0, 'Unexpected ACK value')
                if cpu.state['PC'].value == base + 0x1cb2 then
                    service_acks = service_acks + 1
                    assert(service_acks <= 4, 'Extra service ACK')
                    if service_acks == 2 then
                        assert(space:read_u8(world - 0x88f) == 4, 'Expected service 4')
                        snapshot('frame.bin', 0x100000 - 64, frame_size + 128)
                        snapshot('preack-world.bin', world - 0x5960, 0x5c49)
                        snapshot('service4-world.bin', world - 0x5960, 0x5c49)
                        snapshot('service4-code.bin', base, #bytes)
                        snapshot('code-after.bin', base, #bytes)
                    elseif service_acks == 3 then
                        assert(space:read_u8(world - 0x88f) == 2, 'Expected service 2')
                        snapshot('boot-preack-world.bin', world - 0x5960, 0x5c49)
                        snapshot('boot-preack-code.bin', base, #bytes)
                    elseif service_acks == 4 then
                        assert(space:read_u8(world - 0x88f) == 3, 'Expected service 3')
                        snapshot('bs3-preack-world.bin', world - 0x5960, 0x5c49)
                        snapshot('bs3-preack-code.bin', base, #bytes)
                    end
                end
            elseif off == 0x19 then
                return_writes = return_writes + 1
                assert(return_writes <= 20, 'Extra saved-register return')
            end
            bridge(true, count * 8, off, value)
            record(true, count * 8, off, value)
        end)
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
        cpu.state['SR'].value = 0x2700
        cpu.state['A5'].value = world
        machine.debugger:command('temp0=0')
        if os.getenv('IIE_WRONG_BOOT_P') == '1' then
            cpu.debug:bpset(base + 0x1db8, '1',
                'save "' .. run .. '/boot-p-fault-before.bin",2fa6a0,5c49; '
                .. 'd@310080=pc; pc=201e0c; d@310084=pc; '
                .. 'save "' .. run .. '/boot-p-fault-pc.bin",310080,8; g')
            cpu.debug:bpset(base + 0x1e12, '1',
                'save "' .. run .. '/boot-p-fault-after.bin",2fa6a0,5c49; g')
        end
        cpu.debug:bpset(base + 0x1cae, 'b@(a5-88f)==3', 'temp0=1; g')
        cpu.debug:bpset(base + 0x1c34, 'temp0==1', 'temp0=2; g')
        cpu.debug:bpset(base + 0x2d4, '1', 'pc=20281c; g')
        cpu.debug:bpset(base + 0x281c, 'temp0==2',
            'save "' .. run .. '/world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', #bytes) .. '; '
            .. 'printf "BS3_BOUNDARY pc=%08X sp=%08X",pc,a7; trace off,:maincpu; quit')
        cpu.state['A4'].value = card
        space:write_u32(0x3efffc, base + 0x2c4)
        cpu.state['A7'].value = 0x3efffc
        cpu.state['PC'].value = base + 0x7ae
    elseif frames == 3001 then
        local boundary = assert(io.open(run .. '/world.bin', 'rb'), 'Boot-service boundary not reached')
        boundary:close()
        machine.debugger:command('trace off,:maincpu')
        local file = assert(io.open(run .. '/state.txt', 'w'))
        file:write(string.format('services=%d returns=%d transactions=%d pc=%x sp=%x\n',
            service_acks, return_writes, sequence, cpu.state['PC'].value, cpu.state['A7'].value))
        file:close()
        bus:close()
        registers:close()
        machine:exit()
    end
end)
