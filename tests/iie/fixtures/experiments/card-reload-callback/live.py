#!/usr/bin/env python3
"""Bounded concurrent PDS transport for the reload caller experiment."""
import queue
import subprocess
import threading
import time


def linux(path):
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


class Live:
    def __init__(self, binary, image, folder):
        self.folder = folder
        self.lines = queue.Queue()
        self.output = []
        self.transactions = []
        self.process = subprocess.Popen(['wsl', '--exec', 'vvp', linux(binary),
            '+image=' + linux(image), '+trace=' + linux(folder / 'captures.txt'),
            '+instructions=' + linux(folder / 'instructions.txt'), '+sys_phase=2'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def receive(self, marker):
        deadline = time.monotonic() + 20
        while True:
            line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            assert line is not None, 'RTL exited before ' + marker
            self.output.append(line)
            assert not line.startswith('FATAL:'), line
            if line.startswith(marker):
                return line
            assert time.monotonic() < deadline, marker

    def exchange(self, host, profile, before_ack):
        control = 0xa0 | (profile & 3)
        expected = [[False, 8, 13, 0xa1], [True, 8, 13, control]]
        expected += [[False, 8, 13, control], [True, 8, 13, control]] * 2
        expected += [[False, 8, 1, 224], [False, 8, 1, 224],
            [False, 16, 4, 0xc07d], [False, 8, 12, 1], [True, 8, 12, 0]]
        for sequence, row in enumerate(expected, 1):
            path = self.folder / f'request-{sequence}.txt'
            deadline = time.monotonic() + 20
            while True:
                try:
                    fields = list(map(int, path.read_text().split()))
                    break
                except (FileNotFoundError, PermissionError):
                    assert host.poll() is None and time.monotonic() < deadline, 'Missing host request'
                    time.sleep(0.002)
            assert fields[:4] == [sequence, int(row[0]), row[1], row[2]], fields
            assert fields[4] == (row[3] if row[0] else 0), fields
            if sequence == 11:
                before_ack()
            self.process.stdin.write(' '.join(map(str, fields)) + '\n')
            self.process.stdin.flush()
            response = self.receive('REPLY').split()
            assert list(map(int, response[1:])) == [sequence, row[3]], response
            self.transactions.append(row)
            temporary = path.with_name(f'response-{sequence}.tmp')
            temporary.write_text(f'OK {row[3]}\n', encoding='ascii')
            temporary.replace(path.with_name(f'response-{sequence}.txt'))

    def finish(self):
        self.receive('PASS monitor')
        assert self.process.wait(timeout=10) == 0

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        (self.folder / 'rtl.log').write_text('\n'.join(self.output) + '\n', encoding='ascii')
