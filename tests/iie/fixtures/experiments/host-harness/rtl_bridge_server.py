#!/usr/bin/env python3
"""Original MAME host transactions serviced by the assembled RTL platform."""

import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

from bridge_server import publish
from host_model import ROOT


class RTLService:
    def __init__(self, run, memory, state, executable=None):
        if len(memory) != 0x40000 or state != [0x4000, 0, 0xFC, 0x80]:
            raise ValueError("unsupported RTL handoff")
        self.run = run
        self.sequence = 0
        self.captures = []
        self.pc = None
        self.lines = queue.Queue()
        self.diagnostics = []
        image = run / "rtl-input.hex"
        image.write_text("\n".join(f"{int.from_bytes(memory[i:i+2], 'little'):04x}"
                                   for i in range(0, len(memory), 2)) + "\n", encoding="ascii")
        executable = executable or ROOT / "local/experiments/card-rtl-service/service.vvp"
        if not executable.is_file():
            raise FileNotFoundError(executable)

        def linux(path):
            return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]

        self.process = subprocess.Popen(["wsl", "--exec", "vvp", linux(executable),
                                         "+image=" + linux(image),
                                         "+dump=" + linux(run / "rtl-final.hex")],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)

        def reader():
            for line in self.process.stdout:
                self.lines.put(line.strip())
            self.lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        try:
            assert self.receive() == ["READY"], "RTL did not initialize"
        except Exception:
            self.close()
            raise

    def receive(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError("RTL service exited before response")
            self.diagnostics.append(line)
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "CAP":
                status, address, write, data = fields[1:]
                self.captures.append({"status": int(status, 16), "address": address.upper(),
                                      "write": bool(int(write)),
                                      "data": int(data, 16) if int(write) else None})
                continue
            if fields[0] in ("READY", "REPLY", "STOP", "ERROR"):
                return fields
        raise TimeoutError("RTL service reply deadline")

    def transact(self, request):
        sequence, write, width, offset, value = map(int, request.split())
        if sequence != self.sequence + 1 or write not in (0, 1) or width not in (8, 16):
            raise ValueError("invalid RTL request sequence or width")
        self.process.stdin.write(request.strip() + "\n")
        self.process.stdin.flush()
        fields = self.receive()
        if fields[0] == "STOP":
            assert int(fields[1]) == sequence
            self.pc = fields[2].upper()
            raise RuntimeError(f"RTL boundary ${self.pc}")
        if fields[0] != "REPLY" or int(fields[1]) != sequence:
            raise RuntimeError("unexpected RTL reply: " + " ".join(fields))
        self.sequence = sequence
        return int(fields[2])

    def close(self):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)
        publish(self.run / "rtl-service.log", "\n".join(self.diagnostics) + "\n")


def serve(run, timeout=180, executable=None):
    deadline = time.monotonic() + timeout
    service = None
    sequence = 1
    result = {"scope": "original Macintosh host serviced by PDS/WDC/CDC/native-SDRAM RTL"}
    publish(run / "server.ready", "ready\n")
    try:
        while time.monotonic() < deadline:
            if (run / "server.stop").exists():
                result["stop"] = "runner stopped"
                break
            if service is None:
                if not (run / "handoff.ready").exists():
                    time.sleep(0.002)
                    continue
                memory = (run / "card-memory.bin").read_bytes()
                state = list(map(int, (run / "handoff.txt").read_text().split()))
                service = RTLService(run, memory, state, executable)
            request = run / f"request-{sequence}.txt"
            if not request.exists():
                time.sleep(0.002)
                continue
            try:
                if sequence > 10000:
                    raise RuntimeError("RTL request budget exhausted")
                value = service.transact(request.read_text())
            except Exception as error:
                result["stop"] = f"{type(error).__name__}: {error}"
                result["unsupported_request"] = request.read_text().strip()
                publish(run / f"response-{sequence}.txt", "STOP " + result["stop"] + "\n")
                break
            _, write, width, offset, _ = map(int, request.read_text().split())
            with (run / "bridge.jsonl").open("a", encoding="ascii") as trace:
                trace.write(json.dumps([bool(write), width, offset, value]) + "\n")
            publish(run / f"response-{sequence}.txt", f"OK {value}\n")
            sequence += 1
        else:
            result["stop"] = "RTL bridge wall-clock deadline"
    except Exception as error:
        result["stop"] = f"{type(error).__name__}: {error}"
        publish(run / f"response-{sequence}.txt", "STOP " + result["stop"] + "\n")
    finally:
        if service:
            service.close()
            result.update(transactions=service.sequence, pc=service.pc, captures=service.captures)
        publish(run / "bridge-result.json", json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    serve(args.run.resolve(), executable=args.executable.resolve() if args.executable else None)
