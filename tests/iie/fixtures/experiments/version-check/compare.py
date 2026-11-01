#!/usr/bin/env python3
"""Compare original resource payloads; export guest code only under local/."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INPUTS = {
    "2.2.1": ("local/experiments/firmware-memory/app221/IIe Startup.rsrc",
              "04eaa7546e7fa426f9c07dea5f193de75fb172d83d29dd362d1954b3385266c9"),
    "2.2.2d1": ("local/experiments/startup-runtime/startup/IIe Startup.rsrc",
                "5674f658f77e333a91c309f477e2cfbc703c781cc5f914545974fe44d2ecce8c"),
}


def main():
    spec = importlib.util.spec_from_file_location(
        "resources", ROOT / "fixtures/research/software-bringup/inspect_resources.py")
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    scratch = ROOT / "local/experiments/version-check"
    scratch.mkdir(parents=True, exist_ok=True)
    versions = {}
    for version, (name, expected) in INPUTS.items():
        blob = (ROOT / name).read_bytes()
        if hashlib.sha256(blob).hexdigest() != expected:
            raise ValueError(f"Unexpected input: {name}")
        versions[version] = {(meta["type"], meta["id"]): raw
                             for meta, raw in inspector.resources(blob)}
    old, new = versions.values()
    rows = []
    for kind, rid in sorted(old.keys() | new.keys()):
        a, b = old.get((kind, rid)), new.get((kind, rid))
        rows.append({"type": kind, "id": rid, "identical": a == b,
                     "old_bytes": len(a) if a is not None else None,
                     "new_bytes": len(b) if b is not None else None,
                     "old_sha256": hashlib.sha256(a).hexdigest() if a is not None else None,
                     "new_sha256": hashlib.sha256(b).hexdigest() if b is not None else None})
    for version, entries in versions.items():
        for rid in (0, 1, 2, 7):
            (scratch / f"{version}-CODE-{rid}.bin").write_bytes(entries["CODE", rid])
    tool = Path("C:/Users/Elle/Downloads/mame0289b_x64/unidasm.exe")
    result = {"inputs": INPUTS, "total_resources": len(rows),
              "identical_resources": sum(r["identical"] for r in rows),
              "unidasm_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
              "resources": [r for r in rows if r["type"] in {"CODE", "Conf", "Monx"}]}
    (Path(__file__).parent / "comparison.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(f"Resources identical: {sum(r['identical'] for r in rows)}/{len(rows)}")
    for row in rows:
        if row["type"] in {"Conf", "Monx", "CODE"}:
            print(row["type"], row["id"], row["identical"], row["old_bytes"], row["new_bytes"])
    for version in versions:
        code = scratch / f"{version}-CODE-2.bin"
        listing = subprocess.check_output([str(tool), str(code), "-arch", "m68020"], text=True)
        (scratch / f"{version}-CODE-2.txt").write_text(listing, encoding="ascii")


if __name__ == "__main__":
    main()
