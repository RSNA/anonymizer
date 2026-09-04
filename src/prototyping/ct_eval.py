#!/usr/bin/env python3
"""Backward-compatible CLI entry point. Prefer ``src/prototyping/ct/ct_eval.py``."""

from __future__ import annotations

import sys
from pathlib import Path

# Running this file adds ``src/prototyping`` to sys.path and shadows stdlib ``locale``.
_proto_dir = str(Path(__file__).resolve().parent)
while _proto_dir in sys.path:
    sys.path.remove(_proto_dir)
_src_root = str(Path(__file__).resolve().parents[1])
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from prototyping.ct.ct_eval import main

if __name__ == "__main__":
    sys.exit(main())
