#!/usr/bin/env python3
"""
Face blur visualization POC — generate comparison images and QA report.

Usage::

    uv run python -m prototyping.ffr.face /path/to/ct_head_series

Requires ``ts_seg/face.nii.gz`` (from ``ts_seg_face.py``) and viz dependencies::

    uv sync --extra tseg --extra viz --group dev
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from prototyping.ffr.face.pipeline import run_face_viz_poc

logger = logging.getLogger("prototyping.ffr.face")


def _configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        logger.error("Usage: uv run python -m prototyping.ffr.face /path/to/ct_head_series")
        return 2

    series_dir = Path(args[0])
    if not series_dir.is_dir():
        logger.error("Not a directory: %s", series_dir)
        return 1

    try:
        report = run_face_viz_poc(series_dir)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception("Face viz POC failed: %s", exc)
        return 1

    print(f"report={report}")
    print(f"report_pdf={report.parent / 'report.pdf'}")
    print(f"dicom={series_dir / 'face_blurred'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
