"""Draw predicted PHI boxes on rasterized PDF pages."""

from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw

from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import render_pdf_pages
from anonymizer.view.reports.entity_colors import entity_color_hex
from prototyping.report_phi.pipeline import PredHit


def write_overlays(
    pdf_bytes: bytes,
    hits: list[PredHit],
    out_dir: Path,
    *,
    scale: float = 2.0,
    stem: str = "overlay",
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = render_pdf_pages(pdf_bytes, scale=scale)
    written: list[Path] = []
    by_page: dict[int, list[PredHit]] = {}
    for h in hits:
        by_page.setdefault(h.page_index, []).append(h)

    for i, pil in enumerate(pages):
        img = pil.convert("RGB").copy()
        draw = ImageDraw.Draw(img)
        for h in by_page.get(i, []):
            x0, y0, x1, y1 = h.rect
            box = (x0 * scale, y0 * scale, x1 * scale, y1 * scale)
            color = entity_color_hex(h.label)
            draw.rectangle(box, outline=color, width=3)
            label = f"{h.label}: {(h.text or '')[:40]}"
            ty = max(0, box[1] - 14)
            draw.text((box[0], ty), label, fill=color)
        path = out_dir / f"{stem}_page{i}.png"
        img.save(path)
        written.append(path)
    return written
