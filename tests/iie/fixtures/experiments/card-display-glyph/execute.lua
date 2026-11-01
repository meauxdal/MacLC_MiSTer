local run = assert(os.getenv('IIE_GLYPH_RUN'))
local code = assert(os.getenv('IIE_GLYPH_CODE'))
local base, world, stack = 0x200000, 0x300000, 0x3f0000
local bitmap = world - 0x2412
local frames, pen_x, pen_y = 0, 0, 0
local file = assert(io.open(run .. '/font.bin', 'rb'))
local font = file:read('a')
file:close()
local events = assert(io.open(run .. '/calls.txt', 'w'))
local function word(offset)
    return (font:byte(offset + 1) << 8) | font:byte(offset + 2)
end

emu.register_frame_done(function()
    frames = frames + 1
    if frames ~= 3000 then return end
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    space:read_u32(0xa00000)
    local function load(path, address)
        local input = assert(io.open(path, 'rb'))
        local bytes = input:read('a')
        input:close()
        for i = 1, #bytes do space:write_u8(address + i - 1, bytes:byte(i)) end
        return #bytes
    end
    local size = load(code, base)
    for i = world - 0x5960, world + 0x2e8 do space:write_u8(i, 0x5a) end
    for i = stack - 0x100, stack + 0x10 do space:write_u8(i, 0) end
    local traps = {
        [0x368]=12, [0x36e]=4, [0x372]=0, [0x38a]=4, [0x390]=4,
        [0x39a]=4, [0x3a4]=8, [0x3aa]=4, [0x3b0]=2, [0x3b6]=2,
        [0x3bc]=2, [0x3c2]=2, [0x3d2]=4, [0x3da]=2, [0x3f4]=4,
        [0x3fc]=2, [0x418]=6, [0x4c0]=4, [0x4c6]=4,
    }
    local tap
    tap = space:install_write_tap(0x340000, 0x340003, 'glyph-trap', function()
        local pc = cpu.state['PC'].value - base
        local sp = cpu.state['A7'].value
        local count = assert(traps[pc], string.format('Unexpected trap %x', pc))
        local args = {}
        for offset = 0, count - 2, 2 do args[#args + 1] = string.format('%04x', space:read_u16(sp + offset)) end
        events:write(string.format('%04x %s\n', pc, table.concat(args, ' ')))
        if pc == 0x368 then
            assert(space:read_u32(sp + 8) == world - 0x1218)
            for index, offset in ipairs({4, 6, 0, 2}) do
                space:write_u16(world - 0x1218 + (index - 1) * 2, space:read_u16(sp + offset))
            end
        elseif pc == 0x36e then
            space:write_u32(space:read_u32(sp), 0x321000)
        elseif pc == 0x372 then
            assert(cpu.state['D0'].value == 108)
            cpu.state['A0'].value = 0x320000
        elseif pc == 0x38a then
            space:write_u32(0x320018, 0x321100)
        elseif pc == 0x39a then
            space:write_u32(0x320010, 0)
            space:write_u16(0x320014, space:read_u16(sp))
            space:write_u16(0x320016, space:read_u16(sp + 2))
        elseif pc == 0x3a4 then
            assert(space:read_u32(sp) == world - 0x1218 and space:read_u32(sp + 4) == 0x321100)
        elseif pc == 0x3aa then
            assert(space:read_u32(sp) == 0x320010)
            for offset = 0, 2047 do space:write_u8(bitmap + offset, 0) end
        elseif pc == 0x3d2 or pc == 0x3f4 then
            pen_y, pen_x = space:read_u16(sp), space:read_u16(sp + 2)
        elseif pc == 0x3da or pc == 0x3fc then
            local char = space:read_u16(sp)
            assert(char >= 32 and char <= 159 and pen_x == 7)
            local index = char - word(2)
            local height, stride = word(14), word(24) * 2
            local locations = 26 + height * stride
            local first, last = word(locations + index * 2), word(locations + index * 2 + 2)
            local bearing = font:byte(16 + word(16) * 2 + index * 2 + 1)
            for y = 0, height - 1 do
                for x = first, last - 1 do
                    if (font:byte(26 + y * stride + x // 8 + 1) & (0x80 >> (x % 8))) ~= 0 then
                        local dx = pen_x + bearing + x - first
                        local address = bitmap + (pen_y - word(18) + y) * 2 + dx // 8
                        space:write_u8(address, space:read_u8(address) | (0x80 >> (dx % 8)))
                    end
                end
            end
        elseif pc == 0x418 then
            assert(space:read_u16(sp) == 0x6481 and space:read_u32(sp + 2) == 0x464f4e54)
            space:write_u32(sp + 6, 0)
        end
        cpu.state['A7'].value = sp + count
        return nil
    end)
    -- Retain the tap for the duration of this run.
    _G.glyph_tap = tap
    machine.debugger:command('focus :maincpu')
    machine.debugger.visible_cpu = cpu
    for pc in pairs(traps) do
        cpu.debug:bpset(base + pc, '1', string.format('b@340000=1; pc=%x; g', base + pc + 2))
    end
    cpu.debug:bpset(0x280000, '1',
        'save "' .. run .. '/world.bin",2fa6a0,5c49; '
        .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', size) .. '; '
        .. 'save "' .. run .. '/font-after.bin",350000,4b2; '
        .. 'd@330000=pc; d@330004=a7; d@330008=a6; '
        .. 'd@33000c=d3; d@330010=d5; d@330014=d6; d@330018=d7; '
        .. 'd@33001c=a3; d@330020=a4; save "' .. run .. '/state.bin",330000,24; '
        .. 'trace off,:maincpu; quit')
    load(run .. '/font.bin', 0x350000)
    space:write_u32(stack, 0x280000)
    for _, r in ipairs({'D3', 'D5', 'D6', 'D7', 'A3', 'A4', 'A6'}) do
        cpu.state[r].value = 0x11223344
    end
    machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
    cpu.state['SR'].value = 0x2700
    cpu.state['A5'].value = world
    cpu.state['A7'].value = stack
    cpu.state['PC'].value = base + 0x340
end)
