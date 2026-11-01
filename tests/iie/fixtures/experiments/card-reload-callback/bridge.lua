local run = assert(os.getenv('IIE_BANK_RUN'))
local sequence = 0

return function(write, offset, value)
    sequence = sequence + 1
    assert(sequence <= 11, 'Reload transaction bound')
    local path = run .. '/request-' .. sequence .. '.txt'
    local file = assert(io.open(path .. '.tmp', 'w'))
    file:write(string.format('%d %d %d %d %d\n', sequence, write and 1 or 0,
        offset == 4 and 16 or 8, offset, value))
    file:close()
    assert(os.rename(path .. '.tmp', path))
    local deadline = os.time() + 20
    repeat
        file = io.open(run .. '/response-' .. sequence .. '.txt', 'r')
        if file then
            local response = file:read('a')
            file:close()
            return assert(tonumber(response:match('^OK (%d+)')), response)
        end
    until os.time() >= deadline
    error('RTL reload response deadline')
end
