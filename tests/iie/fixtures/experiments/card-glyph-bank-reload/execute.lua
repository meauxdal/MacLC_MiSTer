local run = assert(os.getenv('IIE_BANK_RUN'))
local driver = tonumber(assert(os.getenv('IIE_BANK_DRIVER')))
local direct = os.getenv('IIE_BANK_DIRECT') == '1'
local world, stack, card = 0x300000, 0x3f0000, 0xe00000
local frames, control = 0, 0xa5
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
        local bytes = file:read('a')
        file:close()
        for i = 1, #bytes do space:write_u8(address + i - 1, bytes:byte(i)) end
    end
    load(run .. '/world-input.bin', world - 0x5960)
    load(run .. '/code-input.bin', 0x200000)
    load(assert(os.getenv('IIE_MAIN_CODE')), 0x280000)
    load(run .. '/settings.bin', 0x362000)
    space:write_u32(0x360000, 0x361000)
    space:write_u32(0x360004, 0x362000)
    space:write_u16(0x361000, 0x1234)
    space:write_u8(0x310020, control)
    for i = 0x370000, 0x37407f do space:write_u8(i, 0x5a) end
    local frame_size = (driver == 5 and 320 or 80) * 480
    for i = 0x100000 - 64, 0x100000 + frame_size + 63 do space:write_u8(i, 0x5a) end
    for i = stack - 0x100, stack + 0x10 do space:write_u8(i, 0) end
    taps[#taps + 1] = space:install_read_tap(card, card + 0x23, 'bank-control-read', function(offset, data, mask)
        assert(offset == card + 12 and mask == 0x00ff0000, 'Unexpected card read')
        return (data & ~mask) | (control << 16)
    end)
    taps[#taps + 1] = space:install_write_tap(card, card + 0x23, 'bank-control-write', function(offset, data, mask)
        assert(offset == card + 12 and mask == 0x00ff0000, 'Unexpected card write')
        control = (data >> 16) & 255
        space:write_u8(0x310020, control)
    end)
    machine.debugger:command('focus :maincpu')
    machine.debugger.visible_cpu = cpu
    cpu.debug:bpset(0x2003a0, '1', 'd@310030=a0; save "' .. run .. '/lock.bin",310030,4; pc=2003a2; g')
    cpu.debug:bpset(0x2003ae, '1', 'd@310030=a0; d@310034=a1; d@310038=d0; save "' .. run .. '/copy.bin",310030,c; pc=290100; g')
    cpu.debug:bpset(0x2003b6, '1', 'd@310030=a0; save "' .. run .. '/unlock.bin",310030,4; pc=2003b8; g')
    local copy = string.char(0x32, 0x3c, 0x00, 0x1f, 0x12, 0xd8, 0x51, 0xc9, 0xff, 0xfc, 0x4e, 0xf9, 0x00, 0x20, 0x03, 0xb0)
    for i = 1, #copy do space:write_u8(0x290100 + i - 1, copy:byte(i)) end
    for phase = 0, 2 do
        local prefix = run .. '/' .. phase .. '-'
        local continuation = 'trace off,:maincpu; quit'
        if phase < 2 then
            local sp = 0x290200 + phase * 8
            space:write_u32(sp, direct and 0x200a7e or 0x290020 + phase * 32)
            if direct then space:write_u32(sp + 4, 0x290020 + phase * 32) end
            continuation = 'w@362006=' .. (phase == 0 and '1' or '0')
                .. '; a7=' .. string.format('%x', sp)
                .. '; pc=' .. (direct and '20035a' or '200774') .. '; g'
        end
        cpu.debug:bpset(0x290000 + phase * 32, '1',
            'save "' .. prefix .. 'world.bin",2fa6a0,5c49; '
            .. 'save "' .. prefix .. 'code-after.bin",200000,' .. (driver == 5 and 'a442' or '75d6') .. '; '
            .. 'save "' .. prefix .. 'main-after.bin",280000,685c; '
            .. 'save "' .. prefix .. 'settings-after.bin",362000,20; '
            .. 'save "' .. prefix .. 'handles.bin",360000,8; '
            .. 'save "' .. prefix .. 'font.bin",361000,2; '
            .. 'save "' .. prefix .. 'card-control.bin",310020,1; '
            .. 'save "' .. prefix .. 'frame.bin",fffc0,' .. string.format('%x', frame_size + 128) .. '; '
            .. 'save "' .. prefix .. 'converted.bin",370000,4080; '
            .. 'save "' .. prefix .. 'traps.bin",310030,c; '
            .. 'd@310000=pc; d@310004=a7; d@310008=a5; d@31000c=a6; '
            .. 'save "' .. prefix .. 'state.bin",310000,10; ' .. continuation)
    end
    space:write_u32(stack - 16, 0x284300)
    space:write_u32(stack - 12, 0x2843d0)
    space:write_u32(stack - 8, 0x200a7e)
    space:write_u32(stack - 4, 0x290000)
    cpu.state['SR'].value = 0x2700
    cpu.state['A5'].value = world
    cpu.state['A6'].value = 0x33445566
    cpu.state['A7'].value = stack - 16
    cpu.state['PC'].value = 0x20035a
    machine.debugger:command('trace ' .. run .. '/trace.txt,:maincpu,noloop')
end)
