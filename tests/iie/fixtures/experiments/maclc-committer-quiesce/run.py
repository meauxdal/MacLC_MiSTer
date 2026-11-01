#!/usr/bin/env python3
"""Bounded Icarus checks of the extracted actual sector committer."""

import hashlib
import json
import shlex
import subprocess

from prepare import HERE, WORK, SOURCE, PIN, prepare


def linux(path):
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def wsl(args):
    return subprocess.run(["wsl", "--", "sh", "-lc", shlex.join(args)],
                          capture_output=True, text=True, timeout=30)


def main():
    prepare()
    runs = []
    for name, baseline, negative, final_tail in [("coordinated", False, False, False),
                                                ("final_ack_tail", False, False, True),
                                                ("immediate_reset", False, True, False),
                                                ("baseline_held_ack", True, False, False)]:
        bench = HERE / "tb_committer.sv"
        source = WORK / ("committer_baseline.v" if baseline else "committer_candidate.v")
        binary = WORK / (name + ".vvp")
        args = ["iverilog", "-g2012", "-s", "tb_committer",
                "-Ptb_committer.BASELINE=" + str(int(baseline)),
                "-Ptb_committer.STOP_FINAL_TAIL=" + str(int(final_tail)),
                "-Ptb_committer.NEGATIVE_RESET=" + str(int(negative))]
        if baseline:
            args.append("-DBASELINE_SOURCE")
        compiled = wsl(args + ["-o", linux(binary), linux(bench), linux(source)])
        assert compiled.returncode == 0, compiled.stderr
        result = wsl(["vvp", linux(binary)])
        output = result.stdout + result.stderr
        if baseline:
            assert result.returncode != 0 and "address skipped" in output, output
        else:
            assert result.returncode == 0 and "PASS" in output, output
        (WORK / (name + ".log")).write_text(output, encoding="ascii")
        runs.append({"name": name, "expected_failure": baseline,
                     "exit_code": result.returncode, "output": output.strip()})
        print(output.strip())
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == PIN
    files = [HERE / "prepare.py", HERE / "run.py", HERE / "tb_committer.sv",
             WORK / "committer_candidate.v", WORK / "committer_baseline.v"]
    manifest = {"source": str(SOURCE), "source_sha256": PIN,
                "hashes": {str(p.relative_to(HERE.parents[2])): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in files}, "runs": runs}
    (HERE / "results.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
