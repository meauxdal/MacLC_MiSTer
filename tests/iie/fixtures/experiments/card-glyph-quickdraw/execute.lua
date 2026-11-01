local run = assert(os.getenv('IIE_QD_RUN'))
local frames = 0

emu.register_frame_done(function()
    frames = frames + 1
    local machine = manager.machine
    local cpu = machine.devices[':maincpu']
    local space = cpu.spaces['program']
    if frames == 3000 then
        machine.debugger:command('focus :maincpu')
        machine.debugger.visible_cpu = cpu
        machine.debugger:command('temp0=0; temp3=0; temp4=0')
        cpu.debug:bpset(space:read_u32(0x5b8),
            '(d0 & ffff)==15 && a0==a6-42 && w@(d@(a6+4)+218)==a06e',
            'temp1=d@(a6+4)-796; temp2=a5; '
            .. 'bpset temp1+796,temp0==0,{'
            .. 'save "' .. run .. '/code-before.bin",temp1,a26; '
            .. 'd@310000=a7; d@310004=a5; d@310008=a6; save "' .. run .. '/caller.bin",310000,c; '
            .. 'temp0=1; d@(a7-4)=temp1+796; a7=a7-4; pc=temp1+340; g}; '
            .. 'bpset temp1+3da,1,{temp3=temp3+1; g}; '
            .. 'bpset temp1+3fc,1,{temp3=temp3+1; g}; '
            .. 'bpset temp1+4a8,1,{temp4=temp4+1; g}; '
            .. 'bpset temp1+796,temp0==1,{'
            .. 'save "' .. run .. '/glyph.bin",temp2-2412,1000; '
            .. 'save "' .. run .. '/code-after.bin",temp1,a26; '
            .. 'd@310000=a7; d@310004=a5; d@310008=a6; d@31000c=temp3; d@310010=temp4; '
            .. 'save "' .. run .. '/result.bin",310000,14; quit}; g')
    elseif frames == 3600 then
        machine.natkeyboard:post_coded('{ENTER}')
    end
end)
