#!/usr/bin/env python3
"""Run the IIe card checks from the MacLC checkout."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    scripts = {
        'upload': 'check_monitor_upload.py',
        'handshake': 'check_handshake_bus.py',
        'runtime': 'check_runtime.py',
        'prepare': 'prepare_runtime.py',
        'fit': 'check_runtime_fit.py',
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=scripts)
    parser.add_argument('arguments', nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    script = Path(__file__).resolve().parent / 'tools' / scripts[args.check]
    return subprocess.call([sys.executable, '-B', str(script), *args.arguments])


if __name__ == '__main__':
    raise SystemExit(main())
