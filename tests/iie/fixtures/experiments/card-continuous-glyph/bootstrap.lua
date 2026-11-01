local run = assert(os.getenv('IIE_DISPATCH_RUN'))
local machine = manager.machine
local cpu = machine.devices[':maincpu']
local space = cpu.spaces['program']
local frames = 0
local caller, world, code2, resource_file
local tap
local function load(path, address)
    local file = assert(io.open(path, 'rb'))
    local bytes = file:read('a')
    file:close()
    for i = 1, #bytes do space:write_u8(address + i - 1, bytes:byte(i)) end
end
local function save(name, address, size)
    local file = assert(io.open(run .. '/' .. name, 'wb'))
    file:write(space:read_range(address, address + size - 1, 8))
    file:close()
end
local function stage_callback(offset, data, mask)
    if mask ~= 0xff000000 and mask ~= 0xff then return end
    local stage = mask == 0xff and (data & 255) or ((data >> 24) & 255)
    print(string.format('INIT_STAGE stage=%d pc=%x', stage, cpu.state['PC'].value))
    if stage == 1 then
        caller = cpu.state['A7'].value
        world = cpu.state['A5'].value
        code2 = cpu.state['PC'].value - 0x796
        resource_file = space:read_u16(world - 0x1204)
        save('glyph-code-before.bin', code2, 0xa26)
        space:write_u32(caller - 4, code2 + 0x796)
        cpu.state['A7'].value = caller - 4
        cpu.state['PC'].value = code2 + 0x340
    elseif stage == 3 then
        save('glyph-code-after.bin', code2, 0xa26)
        save('glyph-live.bin', world - 0x2412, 4096)
        local helper = caller - 0x100
        for i, value in ipairs({0x203c, 0x0005, 0x0000, 0xa71e, 0x4e75}) do
            space:write_u16(helper + (i - 1) * 2, value)
        end
        cpu.debug:bpset(helper + 8, '1', 'temp7=2; b@310000=2; g')
        cpu.state['A7'].value = caller - 0x200
        cpu.state['PC'].value = helper
    elseif stage == 2 then
        local allocation = cpu.state['A0'].value
        assert(allocation ~= 0 and cpu.state['D0'].value == 0, 'Fixture allocation failed')
        local live = {base=allocation, main=allocation + 0x10000,
            frame=allocation + 0x20040, control=allocation + 0x48000, world=world}
        function live.relocate(value)
            if value >= 0x200000 and value <= 0x20a442 then return live.base + value - 0x200000 end
            if value >= 0x280000 and value <= 0x28685c then return live.main + value - 0x280000 end
            if value >= 0x0fffc0 and value <= 0x125880 then return live.frame + value - 0x100000 end
            if value >= 0x2fa6a0 and value <= 0x3002e8 then return world + value - 0x300000 end
            if value >= 0x310000 and value <= 0x310100 then return live.control + value - 0x310000 end
            if value >= 0x360000 and value <= 0x360200 then return live.control + 0x200 + value - 0x360000 end
            if value >= 0x3e0000 and value <= 0x3f0004 then return caller - 0x1000 + value - 0x3f0000 end
            return value
        end
        function live.map_command(command)
            return (command:gsub('%f[%x](%x+)%f[^%x]', function(word)
                local value = tonumber(word, 16)
                local moved = value and live.relocate(value)
                return moved and moved ~= value and string.format('%x', moved) or word
            end))
        end
        _G.iie_live = live
        load(assert(os.getenv('IIE_DISPATCH_CODE')), live.base)
        load(assert(os.getenv('IIE_MAIN_CODE')), live.main)
        for address = world - 0x5812, world - 0x3813 do space:write_u8(address, 0) end
        for address = world - 0x97c, world - 0x96d do space:write_u8(address, 0) end
        space:write_u32(world - 0x88c, 0)
        space:write_u16(world - 0x8ac, 0)
        space:write_u16(world - 0x8bc, 0)
        local driver = tonumber(assert(os.getenv('IIE_DRIVER')))
        space:write_u32(world - 0x1094, live.frame)
        space:write_u16(world - 0x1096, 640)
        space:write_u16(world - 0x10a6, 480)
        space:write_u16(world - 0x10a2, driver == 5 and 4 or 1)
        space:write_u16(world - 0x888, driver == 5 and 320 or 80)
        space:write_u32(world - 0x85a, live.base + 4)
        space:write_u32(live.control + 0x100, live.base)
        space:write_u32(live.control + 0x104, live.main)
        space:write_u32(live.control + 0x108, world)
        space:write_u32(live.control + 0x10c, live.frame)
        space:write_u32(live.control + 0x110, live.relocate(0x3f0000))
        save('context.bin', live.control + 0x100, 20)
        dofile(assert(os.getenv('IIE_LIVE_HOST')))
    elseif stage == 4 then
        _G.iie_finish()
    end
end

emu.register_frame_done(function()
    frames = frames + 1
    if frames == 3000 then
        tap = space:install_write_tap(0x310000, 0x310003, 'continuous-stage', stage_callback)
        _G.iie_stage_tap = tap
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        machine.debugger:command('temp7=0')
        cpu.debug:bpset(space:read_u32(0x5b8),
            '(d0 & ffff)==15 && a0==a6-42 && w@(d@(a6+4)+218)==a06e',
            'temp6=d@(a6+4)-796; '
            .. 'bpset temp6+796,temp7==0,{temp7=1; b@310000=1; g}; '
            .. 'bpset temp6+796,temp7==1,{temp7=3; b@310000=3; g}; g')
    elseif frames == 3600 then
        machine.natkeyboard:post_coded('{ENTER}')
    end
end)
