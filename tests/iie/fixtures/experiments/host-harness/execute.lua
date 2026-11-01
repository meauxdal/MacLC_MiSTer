-- Candidate register responses for original ROM and Startup execution.
local run = assert(os.getenv('IIE_EXEC_RUN'), 'IIE_EXEC_RUN is required')
local frames, index, control, count = 0, 0, 0, 0
local memory, taps = {}, {}
local bus = assert(io.open(run .. '/bus.jsonl', 'w'))
local stopped = false
local bridge = os.getenv('IIE_DIAGNOSTIC_BRIDGE') == '1'
    and dofile('fixtures/experiments/host-harness/diagnostic_bridge.lua') or nil
local diagnostic_started, reset_mask, run_control = false, 0, 0

local function finish()
    local machine = manager.machine
    bus:flush()
    machine.debugger:command('trace off,:maincpu')
    local log = machine.debugger.consolelog
    for i = 1, #log do
        if log[i] then print('DBG ' .. log[i]) end
    end
    local space = machine.devices[':maincpu'].spaces['program']
    local file = assert(io.open(run .. '/ram.bin', 'wb'))
    file:write(space:read_range(0, 0x3fffff, 8))
    file:close()
    print(string.format('BOUNDARY frame=%d transactions=%d index=%04x control=%02x', frames, count, index, control))
    machine:exit()
end

local function address(lane)
    return (((control >> 3) & 1) << 17) | (lane << 16) | index
end

local function access(write, offset, width, value)
    if bridge and (diagnostic_started or (not write and offset == 1 and width == 8)) then
        diagnostic_started = true
        local result, reason = bridge(write, offset, width, value, memory, index, control, reset_mask, run_control)
        if result == nil then
            print('DIAGNOSTIC_STOP ' .. reason)
            stopped = true
            finish()
            return 0
        end
        value = result
    elseif offset == 0x10 and width == 16 then
        if write then
            memory[address(0)] = value >> 8
            memory[address(1)] = value & 0xff
        else
            value = ((memory[address(0)] or 0) << 8) | (memory[address(1)] or 0)
        end
        index = (index + 1) & 0xffff
    elseif (offset == 0x10 or offset == 0x11) and width == 8 then
        if write then memory[address(offset - 0x10)] = value
        else value = memory[address(offset - 0x10)] or 0 end
        index = (index + 1) & 0xffff
    elseif offset == 0x1c and width == 16 then
        if write then index = value else value = index end
    elseif offset == 0x0d and width == 8 then
        if write then control = value else value = control end
    elseif not write and ((offset == 8 and width == 8) or (offset == 4 and width == 16)) then
        value = 0
    elseif not (write and ((width == 8 and (offset == 0x0c or offset == 0x20 or offset == 0x21))
        or (width == 16 and offset == 0x20))) then
        print(string.format('UNMODELED frame=%d write=%s offset=%02x width=%d', frames, tostring(write), offset, width))
        stopped = true
        finish()
        return 0
    end
    if write and width == 8 and offset == 0x21 then reset_mask = value end
    if write and width == 8 and offset == 0x20 then run_control = value end
    count = count + 1
    bus:write(string.format('[%s,%d,%d,%d]\n', tostring(write), width, offset, value))
    return value
end

local function transfer(base, write, offset, data, mask)
    if stopped then return data end
    local space = manager.machine.devices[':maincpu'].spaces['program']
    local bytes = space.data_width // 8
    local first, length = nil, 0
    for lane = 0, bytes - 1 do
        local shift = (bytes - 1 - lane) * 8
        if ((mask >> shift) & 0xff) ~= 0 then
            if ((mask >> shift) & 0xff) ~= 0xff then error('Partial byte mask') end
            if first == nil then first = lane end
            if lane ~= first + length then error('Noncontiguous mask') end
            length = length + 1
        end
    end
    assert(length == 1 or length == 2, 'Unsupported transfer width')
    local shift = (bytes - first - length) * 8
    local value = (data >> shift) & ((1 << (length * 8)) - 1)
    local result = access(write, offset - base + first, length * 8, value)
    if count <= 10 then
        print(string.format('BUS address=%08x mask=%08x write=%s value=%x index=%x', offset, mask, tostring(write), result, index))
    end
    return (data & ~mask) | ((result << shift) & mask)
end

emu.register_frame_done(function()
    frames = frames + 1
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    if frames == 1 then
        print(string.format('SPACE width=%d mask=%x', space.data_width, space.address_mask))
        -- Explicit candidate aliases; not physical decode evidence.
        for _, base in ipairs({0x80000000, 0x80e00000, 0x00e00000}) do
            taps[#taps + 1] = space:install_read_tap(base, base + 0x23, 'iie-read', function(o, d, m)
                return transfer(base, false, o, d, m)
            end)
            taps[#taps + 1] = space:install_write_tap(base, base + 0x23, 'iie-write', function(o, d, m)
                return transfer(base, true, o, d, m)
            end)
        end
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        for _, site in ipairs({0xa4bcd4, 0xa4bcee, 0xa4bf08, 0xa4bf0e}) do
            cpu.debug:bpset(site, '1', 'printf "EXEC pc=%08X d0=%08X d1=%08X d2=%08X sr=%04X mmu=%02X vector8=%08X",pc,d0,d1,d2,sr,b@cb2,d@8; g')
        end
    end
    if frames == 320 then
        local log = machine.debugger.consolelog
        for i = 1, #log do if log[i] then print('BOOT ' .. log[i]) end end
    end
    if frames == 3001 then cpu.debug:wpclear() end
    if stopped or frames == 4800 then
        if not stopped then finish() end
    end
end)

dofile('fixtures/experiments/startup-discovery/trace.lua')
