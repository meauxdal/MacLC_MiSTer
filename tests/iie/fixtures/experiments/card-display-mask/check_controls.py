#!/usr/bin/env python3
"""Replay recorded host requests to reject mask readback and ACK faults."""
import json
import queue
import shlex
import subprocess
import threading
from pathlib import Path
from prepare import HERE, ROOT, WORK, once, sha
from run import linux


def main():
    pins_path = HERE / 'results.json'
    record = json.loads(pins_path.read_text())
    pins = record['inputs_sha256']
    for name, digest in pins.items():
        assert sha(Path(name)) == digest, 'changed mask input: ' + name
    binding = ROOT / 'local/experiments/maclc-iie-banking-build/maclc_iie_binding.sv'
    names = list(pins)
    sources = [WORK / 'tb_mask.sv'] + [Path(name) for name in names[names.index(str(binding)):]]
    sources = [path for path in sources if path.suffix in ('.sv', '.v')]
    registers = WORK / 'card_irq_host_registers.sv'
    text = registers.read_text()
    variants = {
        'zero_readback': once(text, "{1'b0, 6'h21}: rsp_rdata <= {8'b0, host_mask};",
                              "{1'b0, 6'h21}: rsp_rdata <= 0;"),
        'ack_clears_mask': once(text, "{1'b0, 6'h0C}, {1'b0, 6'h18}, {1'b0, 6'h19}: ;",
                                "{1'b0, 6'h18}, {1'b0, 6'h19}: ;\n"
                                "                                {1'b0, 6'h0C}: host_mask <= 0;"),
    }
    controls, inputs = [], [pins_path, HERE / 'check_controls.py']
    for name, source in variants.items():
        broken = WORK / f'{name}.sv'
        broken.write_text(source, encoding='ascii')
        binary = WORK / f'{name}.vvp'
        closure = [broken if path == registers else path for path in sources]
        command = ['iverilog', '-g2012', '-DTB_NO_TRISTATE', '-s', 'tb_card_platform',
                   '-Ptb_card_platform.FAST=1', '-o', linux(binary), *map(linux, closure)]
        subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(command)], check=True, timeout=30)
        process = subprocess.Popen(['wsl', '--exec', 'vvp', linux(binary), '+mask=252',
            '+image=' + linux(ROOT / 'local/experiments/card-monitor-resume/initial.hex'),
            '+trace=' + linux(WORK / f'{name}-captures.txt'),
            '+instructions=' + linux(WORK / f'{name}-instructions.txt')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        lines = queue.Queue()

        def reader():
            for line in process.stdout:
                lines.put(line.strip())
            lines.put(None)

        threading.Thread(target=reader, daemon=True).start()

        def receive(marker):
            while True:
                line = lines.get(timeout=20)
                assert line is not None, 'unexpected simulation exit'
                if line.startswith(marker):
                    return line

        try:
            receive('READY')
            for sequence, (write, width, offset, value) in enumerate(record['runs'][0]['transactions'], 1):
                process.stdin.write(f'{sequence} {int(write)} {width} {offset} {value if write else 0}\n')
                process.stdin.flush()
                reply = receive('REPLY').split()
                if name == 'zero_readback':
                    assert sequence == 1 and int(reply[2]) == 0 and value == 252
                    rejection = 'initial mask readback differs from original recorded request'
                    break
                assert int(reply[2]) == value
            else:
                rejection = receive('FATAL:')
                assert 'PDS read' in rejection and 'offset=00000021' in rejection, rejection
            controls.append({'control': name, 'rejected': rejection})
            print('PASS rejected ' + name)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        inputs.append(broken)
    lint = ['verilator', '--lint-only', '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY',
            '-Wno-UNUSEDSIGNAL', '--timescale-override', '1ns/1ps', '--top-module', 'maclc_iie_binding',
            *map(linux, sources[1:])]
    result = subprocess.run(['wsl', '--', 'sh', '-lc', shlex.join(lint)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    inputs += sources
    (HERE / 'control-results.json').write_text(json.dumps({
        'scope': 'negative RTL controls replay recorded requests; no Macintosh execution',
        'controls': controls, 'lint': 'card/binding -Wall passes with inherited exclusions',
        'inputs_sha256': {str(path): sha(path) for path in inputs}}, indent=2) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()
