"""Tests for face blur HTML/PDF reports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from prototyping.ffr.face.qa import compute_qa_stats
from prototyping.ffr.face.report import write_report


def test_write_report_creates_html_and_pdf(tmp_path: Path) -> None:
    image_path = tmp_path / "J_front_side.png"
    Image.fromarray(np.zeros((120, 80, 3), dtype=np.uint8)).save(image_path)

    before = np.zeros((2, 8, 8), dtype=np.float64)
    after = before.copy()
    mask = np.zeros((2, 8, 8), dtype=bool)
    mask[:, 2:6, 2:6] = True
    after[mask] = 10.0
    stats = compute_qa_stats(before, after, mask)

    html_path = write_report(
        tmp_path,
        {"J_front_side": image_path},
        stats,
        series_dir=tmp_path / "series",
    )
    pdf_path = tmp_path / "report.pdf"

    assert html_path.is_file()
    assert pdf_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert "class=\"mode-desc\"" in html
    assert "posterior / mid / anterior" in html
    assert pdf_path.stat().st_size > 1000
