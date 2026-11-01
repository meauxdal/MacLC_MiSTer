local frames = 0
emu.register_frame_done(function()
    frames = frames + 1
    if frames == 3600 then
        print('Posting Return at frame 3600 to dismiss observed Network Extension modal')
        manager.machine.natkeyboard:post_coded('{ENTER}')
    end
    if frames % 600 == 0 then
        local cpu = manager.machine.devices[':maincpu']
        local space = cpu.spaces['program']
        local count = space:read_u8(0x910)
        if count < 32 then
            local name = ''
            for i = 1, count do name = name .. string.char(space:read_u8(0x910 + i)) end
            print(string.format('frame=%d PC=%08x A5=%08x CurApName=%q',
                frames, cpu.state['PC'].value, cpu.state['A5'].value, name))
        end
        for _, screen in pairs(manager.machine.screens) do
            screen:snapshot('launch-frame-' .. frames .. '.png')
        end
    end
end)
