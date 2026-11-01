local run = assert(os.getenv('IIE_HIRES_RUN'))
local mode = tonumber(assert(os.getenv('IIE_HIRES_MODE')))
local driver = tonumber(assert(os.getenv('IIE_DOUBLE_DRIVER')))
local frames = 0
local world, stack = 0x300000, 0x3f0000
emu.register_frame_done(function()
    frames = frames + 1
    if frames ~= 3000 then return end
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    space:read_u32(0xa00000)
    local function load(path, address)
        local input = assert(io.open(path, 'rb'))
        local data = input:read('a')
        input:close()
        for i = 1, #data do space:write_u8(address + i - 1, data:byte(i)) end
    end
    load(run .. '/world-input.bin', world - 0x5960)
    assert(space:read_u8(world - 0x974) == mode)
    load(run .. '/code-input.bin', 0x200000)
    load(assert(os.getenv('IIE_MAIN_CODE')), 0x280000)
    load(run .. '/image-input.bin', 0x320000)
    load(run .. '/aux-input.bin', 0x350000)
    if os.getenv('IIE_SWAP_BANKS') == '1' then
        load(run .. '/aux-input.bin', 0x320000)
        load(run .. '/image-input.bin', 0x350000)
    end
    load(run .. '/dirty-input.bin', 0x330000)
    load(run .. '/cache-input.bin', 0x340000)
    load(run .. '/frame-input.bin', 0x100000 - 64)
    for i = stack - 0x100, stack + 0x10 do space:write_u8(i, 0) end
    if os.getenv('IIE_BAD_DESTINATION') == '1' then
        space:write_u32(world - 0x85e, space:read_u32(world - 0x85e) + 1)
    end
    machine.debugger:command('focus :maincpu')
    machine.debugger.visible_cpu = cpu
    cpu.debug:bpset(0x290000, '1',
        'save "' .. run .. '/world.bin",2fa6a0,5c49; '
        .. 'save "' .. run .. '/code-after.bin",200000,' .. (driver == 5 and 'a442' or '75d6') .. '; '
        .. 'save "' .. run .. '/main-after.bin",280000,685c; '
        .. 'save "' .. run .. '/image.bin",320000,4080; '
        .. 'save "' .. run .. '/aux.bin",350000,4080; '
        .. 'save "' .. run .. '/dirty.bin",330000,4080; '
        .. 'save "' .. run .. '/cache.bin",340000,7880; '
        .. 'save "' .. run .. '/frame.bin",fffc0,' .. (driver == 5 and '25880' or '9680') .. '; '
        .. 'd@310000=pc; d@310004=a7; d@310008=a5; '
        .. 'save "' .. run .. '/state.bin",310000,c; trace off,:maincpu; quit')
    space:write_u32(stack - 12, 0x2843d0)
    space:write_u32(stack - 8, 0x200a7e)
    space:write_u32(stack - 4, 0x290000)
    cpu.state['SR'].value = 0x2700
    cpu.state['A5'].value = world
    cpu.state['A7'].value = stack - 12
    cpu.state['PC'].value = 0x284300
    machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
end)
