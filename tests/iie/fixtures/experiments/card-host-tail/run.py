#!/usr/bin/env python3
"""Bounded host-tail ordering, timeout and original-byte checks."""
import hashlib
import importlib.util
import json
from pathlib import Path

from diagnostic_tail import ROOT, conf_finish
from host_model import load_conf_resources

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Bus:
    def __init__(self, status=0x08, result=0, states=(255, 0), timeout=None):
        self.status, self.result, self.states = status, result, states
        self.timeout = timeout
        self.stop = -1
        self.polls = 0
        self.events = []

    def read(self, offset, width=8):
        assert width == 8
        if offset == 1:
            assert self.stop >= 0
            value = 0xFF if self.polls == 0 else (0 if self.stop == self.timeout else self.status)
            self.polls += 1
        elif offset == 8:
            assert self.stop in (7, 15) and self.polls == 2
            value = self.states[self.stop // 8]
        else:
            assert offset == 12 and self.stop == 16 and self.polls == 2
            value = self.result
        self.events.append((False, width, offset, value))
        return value

    def write(self, offset, value, width=8):
        assert (offset, value, width) in ((12, 0, 8), (32, 0x0802, 16))
        if offset == 12:
            assert self.stop < 16
            if self.stop >= 0:
                assert self.polls == 2
            self.stop += 1
            self.polls = 0
        self.events.append((True, width, offset, value))


def main():
    spans, inputs = [], [Path(__file__), HERE / 'diagnostic_tail.py',
                        ROOT / 'fixtures/experiments/host-harness/diagnostic_model.py',
                        ROOT / 'fixtures/experiments/host-harness/host_model.py',
                        ROOT / 'fixtures/research/software-bringup/inspect_resources.py']
    expected = {
        (0xE6, 0x106): '610002184a406612422c000c610004f04a406606102c000c7000397c08020020',
        (0x300, 0x33A): ('7807422c000c610002dc4a40662651ccfff20c2c00ff0008661a7807422c000c'
                        '610002c24a40660c51ccfff20c2c000000086704303c000f4e75'),
    }
    spec = importlib.util.spec_from_file_location('tail_resources', inputs[-1])
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    for relative in ('local/experiments/firmware-memory/app221/IIe Startup.rsrc',
                     'local/experiments/startup-runtime/startup/IIe Startup.rsrc'):
        path = ROOT / relative
        load_conf_resources(path)
        original = next(raw for meta, raw in parser.resources(path.read_bytes())
                        if (meta['type'], meta['id']) == ('Conf', 1000))
        for (start, end), hex_bytes in expected.items():
            assert original[start:end] == bytes.fromhex(hex_bytes), (relative, start)
            spans.append({'fork': relative, 'start': f'{start:04X}', 'end': f'{end:04X}',
                          'sha256': hashlib.sha256(original[start:end]).hexdigest()})
        inputs.append(path)
    cases = 0
    for status in range(1, 256):
        bus = Bus(status=status)
        assert conf_finish(bus) == 0
        golden = []
        for stop in range(17):
            golden += [(True, 8, 12, 0), (False, 8, 1, 255), (False, 8, 1, status)]
            if stop in (7, 15):
                golden.append((False, 8, 8, 255 if stop == 7 else 0))
        golden += [(False, 8, 12, 0), (True, 16, 32, 0x0802)]
        assert bus.events == golden
        cases += 1
    for value in range(256):
        bus = Bus(result=value)
        assert conf_finish(bus) == 0 and bus.events[-2:] == [
            (False, 8, 12, value), (True, 16, 32, 0x0802)]
        cases += 1
        for group, required in ((0, 255), (1, 0)):
            if value == required:
                continue
            states = (value, 0) if group == 0 else (255, value)
            bus = Bus(states=states)
            assert conf_finish(bus) == 15 and bus.stop == (7 if group == 0 else 15)
            assert bus.events[-2:] == [(False, 8, 8, value), (True, 16, 32, 0x0802)]
            cases += 1
    for stop in range(17):
        bus = Bus(timeout=stop)
        assert conf_finish(bus) == (2 if stop == 16 else 15)
        assert bus.stop == stop and bus.polls == 1002
        assert bus.events[-1] == (True, 16, 32, 0x0802)
        assert not any(not write and offset == 12 for write, _, offset, _ in bus.events)
        cases += 1
    result = {'cases': cases, 'original_spans': spans,
              'checks': 'ordered success, all nonzero statuses, all final data, aggregate failures, every timeout, cleanup',
              'inputs_sha256': {path.relative_to(ROOT).as_posix(): sha(path) for path in inputs}}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print(f'PASS {cases} host-tail cases; original spans match both forks')


if __name__ == '__main__':
    main()
