#!/usr/bin/env python3
"""Execute the original CNmc slot read-reply and write-ACK stubs on TG68K."""
import json
from pathlib import Path

from check_runtime import linux, run, run_process
from prepare_runtime import ROOT, WORK, sha


def main():
    repo = ROOT.parents[1]
    work = WORK
    work.mkdir(parents=True, exist_ok=True)
    metadata = ROOT / 'local/experiments/startup-protocol/resources.json'
    fork = ROOT / 'local/experiments/startup-protocol/app221/IIe Startup.rsrc'
    item = next(r for r in json.loads(metadata.read_text())['resources']
                if r['type'] == 'CNmc' and r['id'] == 5632)
    raw = fork.read_bytes()
    payload = raw[item['fork_offset']:item['fork_offset'] + item['size']]
    assert payload[0x6c:0x7a] == bytes.fromhex('1973201800194e75422c000c4e75')

    # Synthetic table and endpoint bases; original routine bytes are unchanged.
    program = b''
    program += bytes.fromhex('267c') + (0x3000).to_bytes(4, 'big')
    program += bytes.fromhex('287c') + (0x4000).to_bytes(4, 'big')
    program += bytes.fromhex('7401')  # MOVEQ #1,D2
    program += bytes.fromhex('4eb9') + (0x2006c).to_bytes(4, 'big')
    program += bytes.fromhex('287c') + (0x4000).to_bytes(4, 'big')
    program += bytes.fromhex('4eb9') + (0x20074).to_bytes(4, 'big')
    program += bytes.fromhex('13fc005a0000900060fe')

    def make_image(name, reply, ack_base=0x4000):
        code = bytearray(program)
        code[22:26] = ack_base.to_bytes(4, 'big')
        memory = bytearray(0x40000)
        memory[:8] = bytes.fromhex('0000800000000100')
        memory[0x100:0x100 + len(code)] = code
        memory[0x3019] = reply
        memory[0x20000 + 0x6c:0x20000 + 0x6c + len(payload[0x6c:0x7a])] = payload[0x6c:0x7a]
        image = work / name
        image.write_text(''.join(f'{int.from_bytes(memory[i:i+2], "big"):04x}\n'
                                 for i in range(0, len(memory), 2)), encoding='ascii')
        return image

    image = make_image('slot-host.hex', 0x5a)
    wrong_reply = make_image('slot-host-wrong-reply.hex', 0)
    wrong_offset = make_image('slot-host-wrong-offset.hex', 0x5a, 0x4001)

    bench = ROOT / 'tools/tb_slot_host.sv'
    host = [repo / 'rtl/tg68k' / n for n in
            ('TG68K_Pack.sv', 'TG68K_ALU.v', 'TG68KdotC_Kernel.v', 'tg68k.v')]
    binary = work / 'slot-host.vvp'
    run(['iverilog', '-g2012', '-s', 'tb_slot_host', '-o', linux(binary),
         linux(bench), *map(linux, host)])
    command = ['vvp', linux(binary), '+image=' + linux(image)]
    output = run(command)
    controls = {}
    for name, input_image, expected in (('wrong-reply', wrong_reply, 'original read reply mismatch'),
                                        ('wrong-offset', wrong_offset, 'original host write mismatch')):
        result = run_process(['vvp', linux(binary), '+image=' + linux(input_image)])
        assert result.returncode and expected in result.stdout, result.stdout + result.stderr
        controls[name] = result.stdout
        print('PASS rejected ' + name)
    record = {'result': output, 'controls': controls,
              'scope': 'Original CNmc 5632 read-reply and write-ACK routines execute on TG68K with synthetic entry registers and an isolated captured endpoint; no card PDS transaction or peripheral service',
              'sha256': {str(p): sha(p) for p in [metadata, fork, bench, image, wrong_reply, wrong_offset, *host, Path(__file__)]}}
    (work / 'slot-host.json').write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
