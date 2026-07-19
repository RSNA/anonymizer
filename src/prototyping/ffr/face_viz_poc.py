#!/usr/bin/env python3
"""Shim: ``uv run python src/prototyping/ffr/face_viz_poc.py <series_dir>``."""

from prototyping.ffr.face.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
