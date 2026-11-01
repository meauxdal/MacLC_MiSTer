-- File transport starts only after the original stream prelude.
local run = assert(os.getenv('IIE_EXEC_RUN'))
local sequence, initialized = 0, false

local function publish(name, data)
    local file = assert(io.open(run .. '/' .. name .. '.tmp', 'wb'))
    file:write(data)
    file:close()
    assert(os.rename(run .. '/' .. name .. '.tmp', run .. '/' .. name))
end

return function(write, offset, width, value, memory, index, control, reset_mask, run_control)
    if not initialized then
        local chunks = {}
        for base = 0, 0x3ffff, 1024 do
            local bytes = {}
            for address = base, base + 1023 do
                bytes[#bytes + 1] = string.char(memory[address] or 0)
            end
            chunks[#chunks + 1] = table.concat(bytes)
        end
        publish('card-memory.bin', table.concat(chunks))
        publish('handoff.txt', string.format('%d %d %d %d', index, control, reset_mask, run_control))
        publish('handoff.ready', 'ready\n')
        initialized = true
    end
    sequence = sequence + 1
    publish('request-' .. sequence .. '.txt', string.format('%d %d %d %d %d\n',
        sequence, write and 1 or 0, width, offset, value))
    local deadline = os.time() + 15
    repeat
        local file = io.open(run .. '/response-' .. sequence .. '.txt', 'r')
        if file then
            local response = file:read('*a')
            file:close()
            local result = response:match('^OK (%d+)')
            if result then return tonumber(result) end
            return nil, response:gsub('[\r\n]', '')
        end
    until os.time() >= deadline
    return nil, 'STOP bridge response deadline'
end
