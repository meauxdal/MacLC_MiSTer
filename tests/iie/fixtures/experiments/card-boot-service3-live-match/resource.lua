        for i = 0x3600c0, 0x36018d do space:write_u8(i, 0x5a) end
        overlay(assert(os.getenv('IIE_MATCH_RESOURCE')), 0x360100)
        space:write_u32(0x360000, 0x360100)
        cpu.debug:bpset(base + 0x1dd8, '1',
            'temp1=temp1+1; save "' .. run .. '/resource-stack.bin",a7,a; '
            .. 'd@(a7+6)=360000; a7=a7+6; pc=201dda; g')
        cpu.debug:bpset(base + 0x1de2, '1',
            'temp2=temp2+1; d@310000=a0; save "' .. run .. '/lock.bin",310000,4; pc=201de4; g')
        local unlock = 'temp3=temp3+1; d@310000=a0; save "' .. run .. '/unlock.bin",310000,4; '
            .. 'd@310000=temp1; d@310004=temp2; d@310008=temp3; '
            .. 'save "' .. run .. '/resource-traps.bin",310000,c; pc=201e0c; '
        if os.getenv('IIE_SKIP_MATCH_P') == '1' then
            unlock = unlock .. 'save "' .. run .. '/fault-before.bin",2fa6a0,5c49; '
                .. 'd@310080=pc; pc=201e12; d@310084=pc; '
                .. 'save "' .. run .. '/fault-pc.bin",310080,8; '
                .. 'save "' .. run .. '/fault-after.bin",2fa6a0,5c49; '
        end
        cpu.debug:bpset(base + 0x1e0a, '1', unlock .. 'g')
