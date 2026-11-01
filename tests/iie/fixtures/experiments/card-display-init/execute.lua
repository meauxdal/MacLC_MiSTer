local run = assert(os.getenv('IIE_INIT_RUN'))
local driver = tonumber(assert(os.getenv('IIE_INIT_DRIVER')))
local code = assert(os.getenv('IIE_INIT_CODE'))
local main = assert(os.getenv('IIE_INIT_MAIN'))
local frames = 0
local base, caller, world, stack = 0x200000, 0x280000, 0x300000, 0x3f0000
local stride = driver == 5 and 320 or 80

emu.register_frame_done(function()
    frames = frames + 1
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    if frames == 3000 then
        space:read_u32(0x00a00000)
        local function load(path, address, name)
            local file = assert(io.open(path, 'rb'))
            local bytes = file:read('a')
            file:close()
            for i = 1, #bytes do space:write_u8(address + i - 1, bytes:byte(i)) end
            file = assert(io.open(run .. '/' .. name, 'wb'))
            file:write(space:read_range(address, address + #bytes - 1, 8))
            file:close()
            return #bytes
        end
        local size = load(code, base, 'loaded.bin')
        load(main, caller, 'main-loaded.bin')
        for i = world - 0x5960, world + 0x2e8 do space:write_u8(i, 0) end
        for i = stack - 0x100, stack + 0x10 do space:write_u8(i, 0) end
        space:write_u32(world - 0x1208, 0x320000)
        space:write_u32(0x320002, 0x320100)
        space:write_u32(0x320100, 0x320200)
        space:write_u16(0x320204, 0xc000 | stride)
        space:write_u32(world - 0x85a, base + 4)
        space:write_u32(world - 0x1094, 0x100000)
        space:write_u16(world - 0x1096, 640)
        space:write_u16(world - 0x10a6, 480)
        space:write_u16(world - 0x10a2, driver == 5 and 4 or 1)
        space:write_u16(world - 0x1204, 0x1234)
        space:write_u16(0xa5a, 0x5678)
        space:write_u32(world - 0x8c0, 0xdeadbeef)
        for i = 3, 7 do cpu.state['D' .. i].value = 0x11220000 + i end
        cpu.state['A6'].value = 0x33445566
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        machine.debugger:command('temp0=0')
        local resource = 'temp0=temp0+1; '
            .. 'save "' .. run .. '/resource-stack.bin",a7,c; '
            .. 'save "' .. run .. '/resource-file.bin",a5a,2; '
            .. 'printf "RESOURCE type=%08X id=%04X file=%04X",d@(a7+2),w@a7,w@a5a; '
            .. 'd@(a7+6)=0; a7=a7+6; pc=2000d2; g'
        cpu.debug:bpset(base + 0xd0, '1', resource)
        cpu.debug:bpset(caller + 0x42f2, '1',
            'save "' .. run .. '/world.bin",2fa6a0,5c49; '
            .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', size) .. '; '
            .. 'save "' .. run .. '/main-after.bin",280000,685c; '
            .. 'save "' .. run .. '/low.bin",a5a,2; '
            .. 'printf "RETURN pc=%08X sp=%08X a6=%08X traps=%d d3=%08X d4=%08X d5=%08X d6=%08X d7=%08X",pc,a7,a6,temp0,d3,d4,d5,d6,d7; '
            .. 'trace off,:maincpu; quit')
        machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
        cpu.state['SR'].value = 0x2700
        cpu.state['A5'].value = world
        cpu.state['A7'].value = stack
        cpu.state['PC'].value = caller + 0x42d4
    elseif frames == 3001 then
        local file = assert(io.open(run .. '/state.txt', 'w'))
        file:write(string.format('pc=%x sp=%x a6=%x d3=%x d4=%x d5=%x d6=%x d7=%x\n',
            cpu.state['PC'].value, cpu.state['A7'].value, cpu.state['A6'].value,
            cpu.state['D3'].value, cpu.state['D4'].value, cpu.state['D5'].value,
            cpu.state['D6'].value, cpu.state['D7'].value))
        file:close()
        machine:exit()
    end
end)
