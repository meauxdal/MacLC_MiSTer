#!/usr/bin/env python3
"""Retain glyph bank 1 through the live service-4 continuation."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'local/experiments/card-reload-service4-bank'
PARENT = ROOT / 'fixtures/experiments/card-reload-service4'
spec = importlib.util.spec_from_file_location('service4_parent_prepare', PARENT / 'prepare.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
once, sha = parent.once, parent.sha


def prepare():
    parent.WORK = WORK
    sources, image, inputs = parent.prepare()
    path = WORK / 'execute.lua'
    host = once(path.read_text(), 'local/experiments/card-reload-service4/bridge.lua',
                'local/experiments/card-reload-service4-bank/bridge.lua')
    host = once(host, "(phase == 0 and '1' or '0')", "'1'")
    path.write_text(host, encoding='ascii')
    return sources, image, inputs + [HERE / 'prepare.py']
