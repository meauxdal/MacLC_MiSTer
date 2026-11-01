local run = assert(os.getenv('IIE_DISPATCH_RUN'))
local sequence = 0

return function(write, width, offset, value)
    sequence = sequence + 1
    assert(sequence <= 5, 'Host subset transaction bound')
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
