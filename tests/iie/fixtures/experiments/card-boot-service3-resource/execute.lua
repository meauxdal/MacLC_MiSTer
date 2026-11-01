local run = assert(os.getenv('IIE_BS3_RUN'))
local code = assert(os.getenv('IIE_BS3_CODE'))
local profile = assert(os.getenv('IIE_BS3_PROFILE'))
local fault = os.getenv('IIE_BS3_FAULT') == '1'
local frame_size = tonumber(assert(os.getenv('IIE_FRAME_SIZE')))
local base, world = 0x200000, 0x300000
local frames = 0
local taps = {}
emu.register_frame_done(function()
    frames = frames + 1
    if frames ~= 3000 then return end
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    space:read_u32(0xa00000)
    local function load(path, address)
        local file = assert(io.open(path, 'rb'))
        local bytes = file:read('a'); file:close()
        for i = 1, #bytes do space:write_u8(address + i - 1, bytes:byte(i)) end
        return #bytes
    end
    local function snapshot(name, address, size)
        local file = assert(io.open(run .. '/' .. name, 'wb'))
        file:write(space:read_range(address, address + size - 1, 8)); file:close()
    end
    local size = load(code, base)
    snapshot('loaded.bin', base, size)
    load(assert(os.getenv('IIE_INIT_CODE')), base)
    load(assert(os.getenv('IIE_INIT_WORLD')), world - 0x5960)
    for i = 0x3600c0, 0x36018d do space:write_u8(i, 0x5a) end
    local resource_size = load(assert(os.getenv('IIE_BS3_RESOURCE')), 0x360100)
    assert(resource_size == 77)
    space:write_u32(0x360000, 0x360100)
    space:write_u32(world - 0x1236, 0xe00000)
    space:write_u8(world - 0x5814, profile == 'override' and 0xa5 or 0)
    space:write_u16(world - 0x86c, profile == 'special' and 0xa5b1 or 0xa5b6)
    space:write_u8(world - 0x894, profile == 'special' and 0xc0 or 0xc4)
    space:write_u8(world - 0x891, 0xa5)
    space:write_u16(world - 0x97c, 0x5a5a)
    space:write_u32(0x3f0000, 0x280000)
    for i = 0x100000 - 64, 0x100000 + frame_size + 63 do space:write_u8(i, 0x5a) end
    snapshot('before-world.bin', world - 0x5960, 0x5c49)
    snapshot('before-code.bin', base, size)
    local reads = assert(io.open(run .. '/reads.txt', 'w')); reads:setvbuf('no')
    taps[#taps + 1] = space:install_read_tap(0xe00000, 0xe00023, 'bs3-read', function(offset, data, mask)
        assert(offset == 0xe00020 and mask == 0x00ff0000, 'Unexpected card read')
        reads:write('21 20\n')
        return (data & ~mask) | (0x20 << 16)
    end)
    taps[#taps + 1] = space:install_write_tap(0xe00000, 0xe00023, 'bs3-write', function()
        error('Unexpected card write')
    end)
    machine.debugger:command('focus :maincpu')
    machine.debugger.visible_cpu = cpu
    machine.debugger:command('temp0=0; temp1=0; temp2=0')
    cpu.debug:bpset(base + 0x1dd8, '1',
        'temp0=temp0+1; save "' .. run .. '/resource-stack.bin",a7,a; '
        .. 'd@(a7+6)=' .. (profile == 'absent' and '0' or '360000') .. '; a7=a7+6; pc=201dda; g')
    cpu.debug:bpset(base + 0x1de2, '1',
        'temp1=temp1+1; d@310000=a0; save "' .. run .. '/lock.bin",310000,4; pc=201de4; g')
    local unlock = 'temp2=temp2+1; d@310000=a0; save "' .. run .. '/unlock.bin",310000,4; '
    if fault then
        unlock = unlock .. 'pc=201e0c; save "' .. run .. '/fault-before.bin",2fa6a0,5c49; '
            .. 'd@310080=pc; pc=201e12; d@310084=pc; save "' .. run .. '/fault-pc.bin",310080,8; '
            .. 'save "' .. run .. '/fault-after.bin",2fa6a0,5c49; g'
    else
        unlock = unlock .. 'pc=201e0c; g'
    end
    cpu.debug:bpset(base + 0x1e0a, '1', unlock)
    cpu.debug:bpset(0x280000, '1',
        'save "' .. run .. '/world.bin",2fa6a0,5c49; '
        .. 'save "' .. run .. '/code-after.bin",200000,' .. string.format('%x', size) .. '; '
        .. 'save "' .. run .. '/resource-after.bin",3600c0,ce; '
        .. 'save "' .. run .. '/frame.bin",fffc0,' .. string.format('%x', frame_size + 128) .. '; '
        .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=temp0; d@310010=temp1; d@310014=temp2; '
        .. 'save "' .. run .. '/state.bin",310000,18; trace off,:maincpu; quit')
    machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
    cpu.state['SR'].value = 0x2700
    cpu.state['A5'].value = world
    cpu.state['D1'].value = 0
    cpu.state['A7'].value = 0x3f0000
    cpu.state['PC'].value = base + 0x1d8a
end)
