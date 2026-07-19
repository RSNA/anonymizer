from __future__ import annotations

import html
import json
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image

from prototyping.ffr.face.models import QaStats
from prototyping.ffr.face.viz import VIZ_MODES
from prototyping.ffr.face.viz.modes import MODE_DESCRIPTIONS

_REPORT_CSS = """
    body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 960px; line-height: 1.45; }
    h1 { line-height: 1.25; margin-bottom: 0.75rem; }
    h2 { line-height: 1.35; margin: 0 0 0.5rem; }
    .qa { padding: 1rem; border-radius: 8px; line-height: 1.6; }
    section { margin: 2rem 0; border-top: 1px solid #ccc; padding-top: 1rem; }
    .mode-desc { line-height: 1.55; margin: 0 0 1rem; max-width: 60rem; }
    section img { display: block; margin-top: 0.25rem; max-width: 100%; height: auto; }
"""


def _qa_status(stats: QaStats) -> str:
    return (
        "PASS — no changes outside face mask"
        if stats.outside_clean
        else "FAIL — changes detected outside face mask"
    )


def _qa_background(stats: QaStats) -> str:
    return "#e8f5e9" if stats.outside_clean else "#ffebee"


def _mode_description_html(mode_id: str) -> str:
    if mode_id == "J_front_side":
        return (
            "Coronal and sagittal slabs at three positions each "
            "(posterior / mid / anterior and right / mid / left):<br>"
            "before vs after blur. Green = TotalSegmentator face mask outline (QA)."
        )
    return html.escape(MODE_DESCRIPTIONS.get(mode_id, ""))


def _qa_summary_lines(stats: QaStats) -> list[str]:
    return [
        _qa_status(stats),
        f"max |diff| outside mask: {stats.max_abs_diff_outside:.6g}",
        f"violating voxels outside mask: {stats.n_violating_voxels} / {stats.n_outside_voxels}",
        f"face voxels: {stats.n_face_voxels}",
        f"mean |diff| inside mask: {stats.mean_abs_diff_inside:.4g} HU",
    ]


def write_report_pdf(
    output_dir: Path,
    rendered: dict[str, Path],
    stats: QaStats,
    *,
    series_dir: Path,
) -> Path:
    """Build a simple PDF mirror of ``report.html`` for distribution."""
    pdf_path = output_dir / "report.pdf"
    qa_lines = _qa_summary_lines(stats)

    with PdfPages(pdf_path) as pdf:
        cover = plt.figure(figsize=(8.5, 11))
        cover.text(0.5, 0.88, "Face blur visualization POC", ha="center", fontsize=16, weight="bold")
        cover.text(0.5, 0.82, f"Series: {series_dir}", ha="center", fontsize=9, wrap=True)
        y = 0.72
        for line in qa_lines:
            weight = "bold" if line.startswith(("PASS", "FAIL")) else "normal"
            cover.text(0.08, y, line, ha="left", va="top", fontsize=10, weight=weight)
            y -= 0.045
        pdf.savefig(cover, bbox_inches="tight")
        plt.close(cover)

        for mode_id in VIZ_MODES:
            image_path = rendered.get(mode_id)
            if image_path is None or not image_path.is_file():
                continue

            desc = MODE_DESCRIPTIONS.get(mode_id, "")
            if mode_id == "J_front_side":
                desc = (
                    "Coronal and sagittal slabs at three positions each "
                    "(posterior / mid / anterior and right / mid / left): "
                    "before vs after blur. Green = TotalSegmentator face mask outline (QA)."
                )
            wrapped = "\n".join(textwrap.wrap(desc, width=95))

            page = plt.figure(figsize=(8.5, 11))
            page.text(0.5, 0.97, mode_id, ha="center", va="top", fontsize=13, weight="bold")
            page.text(
                0.05,
                0.925,
                wrapped,
                ha="left",
                va="top",
                fontsize=9,
                linespacing=1.45,
                wrap=True,
            )
            image_axes = page.add_axes((0.03, 0.04, 0.94, 0.84))
            image_axes.imshow(Image.open(image_path))
            image_axes.axis("off")
            pdf.savefig(page, bbox_inches="tight")
            plt.close(page)

    return pdf_path


def write_report(
    output_dir: Path,
    rendered: dict[str, Path],
    stats: QaStats,
    *,
    series_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"

    qa_json = {
        "outside_clean": stats.outside_clean,
        "max_abs_diff_outside": stats.max_abs_diff_outside,
        "n_violating_voxels": stats.n_violating_voxels,
        "n_outside_voxels": stats.n_outside_voxels,
        "n_face_voxels": stats.n_face_voxels,
        "mean_abs_diff_inside": stats.mean_abs_diff_inside,
    }
    (output_dir / "qa_summary.json").write_text(json.dumps(qa_json, indent=2), encoding="utf-8")

    status = _qa_status(stats)
    qa_lines = _qa_summary_lines(stats)[1:]
    sections: list[str] = []
    for mode_id in VIZ_MODES:
        image_path = rendered.get(mode_id)
        if image_path is None:
            continue
        rel = html.escape(image_path.name)
        desc = _mode_description_html(mode_id)
        sections.append(
            f"<section><h2>{html.escape(mode_id)}</h2>"
            f'<p class="mode-desc">{desc}</p>'
            f'<img src="{rel}" alt="{rel}" /></section>'
        )

    qa_body = "<br />\n    ".join(html.escape(line) for line in qa_lines)
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Face blur viz POC</title>
  <style>
{_REPORT_CSS}
    .qa {{ background: {_qa_background(stats)}; }}
  </style>
</head>
<body>
  <h1>Face blur visualization POC</h1>
  <p>Series: <code>{html.escape(str(series_dir))}</code></p>
  <div class="qa"><strong>{html.escape(status)}</strong><br />
    {qa_body}
  </div>
  {"".join(sections)}
</body>
</html>
"""
    report_path.write_text(body, encoding="utf-8")
    write_report_pdf(output_dir, rendered, stats, series_dir=series_dir)
    return report_path
