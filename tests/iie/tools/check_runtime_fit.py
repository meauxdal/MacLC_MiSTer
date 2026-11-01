#!/usr/bin/env python3
"""Check fresh fitter and timing summaries for the combined runtime target."""
import json
from pathlib import Path
import re

from prepare_runtime import MACLC, WORK, sha


def main():
    manifest = WORK / 'sources.json'
    sources = json.loads(manifest.read_text())['sha256']
    for name, expected in sources.items():
        assert sha(Path(name)) == expected, f'Source changed since preparation: {name}'
    output = MACLC / 'output_files'
    fit = output / 'MacLC.fit.summary'
    timing = output / 'MacLC.sta.summary'
    rbf = output / 'MacLC.rbf'
    newest = max([manifest.stat().st_mtime, *(Path(p).stat().st_mtime for p in sources)])
    for path in (fit, timing, rbf):
        if not path.is_file() or path.stat().st_mtime < newest:
            raise SystemExit(f'Fit is unverified. Run the full runtime build. Missing or stale output: {path}')
    text = fit.read_text()
    assert re.search(r'^Fitter Status\s*:\s*Successful', text, re.M), 'Fitter did not succeed'
    slacks = [float(value) for value in re.findall(r'^Slack\s*:\s*(-?[\d.]+)', timing.read_text(), re.M)]
    assert slacks and min(slacks) >= 0, f'Timing failed or absent: {slacks}'
    for line in text.splitlines():
        if any(label in line for label in ('Logic utilization', 'Total RAM Blocks', 'Total block memory bits', 'Total DSP Blocks')):
            print(line)
    print(f'Minimum reported timing slack: {min(slacks):.3f} ns')
    print(f'PASS fresh combined fit and reported timing summaries: {rbf}')


if __name__ == '__main__':
    main()
