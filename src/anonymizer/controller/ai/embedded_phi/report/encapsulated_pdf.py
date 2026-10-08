"""Encapsulated PDF text extract + rewrite (plain-text PDF replacement on Save)."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from pydicom import Dataset, dcmread
from pydicom.errors import InvalidDicomError

from anonymizer.controller.ai.embedded_phi.report.content_text import TextSlot
from anonymizer.utils.storage import get_dcm_files

logger = logging.getLogger(__name__)

PDF_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.104.1"

# Helvetica page: 612×792, 12pt, ~90 chars/line, ~60 lines/page.
_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_MARGIN = 50
_FONT_SIZE = 11
_LINE_HEIGHT = 14
_CHARS_PER_LINE = 90
_LINES_PER_PAGE = 48

_LABEL_VALUE = re.compile(r"^(.+?:)\s*$")


def encapsulated_pdf_bytes(ds: Dataset) -> bytes | None:
    """Return raw PDF bytes from ``EncapsulatedDocument``, or ``None`` when absent / not a PDF."""
    blob = ds.get("EncapsulatedDocument")
    if not blob:
        return None
    if str(ds.get("MIMETypeOfEncapsulatedDocument", "application/pdf")).lower() != "application/pdf":
        return None
    return bytes(blob).rstrip(b"\x00")


def format_extracted_pdf_text(raw: str) -> str:
    """
    Normalize pypdf layout extract into readable paragraphs for display and NER.

    Clinical PDFs often emit tab-separated tokens and put labels/values on alternate
    lines (``Patient:\\nMnikathi Mxolisi``). Full sentences/paragraphs give the NER
    engine usable context; fractured one-token lines do not.
    """
    if not raw or not raw.strip():
        return ""
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        cleaned = re.sub(r"\s+:", ":", cleaned)  # "Gender :" → "Gender:"
        lines.append(cleaned)

    paired: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line and _LABEL_VALUE.match(line) and nxt and not _LABEL_VALUE.match(nxt):
            paired.append(f"{line} {nxt}")
            i += 2
            continue
        paired.append(line)
        i += 1

    # Collapse runs of blank lines; keep paragraph breaks between prose blocks.
    out: list[str] = []
    blank = False
    for line in paired:
        if not line:
            blank = True
            continue
        if out and blank:
            out.append("")
        blank = False
        out.append(line)
    return "\n".join(out).strip()


def extract_pdf_text(ds: Dataset) -> str:
    """Return the text layer of ``EncapsulatedDocument`` or ``""`` (no pypdf, scanned/image PDF, or not a PDF)."""
    data = encapsulated_pdf_bytes(ds)
    if not data:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a declared dependency
        logger.warning("report_pdf: pypdf not installed; PDF text extraction skipped")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception:  # noqa: BLE001 - malformed PDFs must never crash the review window
        logger.exception("report_pdf: text extraction failed")
        return ""
    raw = "\n\n".join(p.strip() for p in pages if p.strip())
    return format_extracted_pdf_text(raw)


def render_pdf_pages(data: bytes, *, scale: float = 1.5) -> list[Image.Image]:
    """Rasterize PDF bytes to PIL images (one per page). Empty list when pypdfium2 is missing."""
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover - declared dependency
        logger.warning("report_pdf: pypdfium2 not installed; PDF page render skipped")
        return []
    try:
        doc = pdfium.PdfDocument(data)
        pages: list[Image.Image] = []
        for i in range(len(doc)):
            page = doc[i]
            bitmap = page.render(scale=scale)
            pages.append(bitmap.to_pil())
        return pages
    except Exception:  # noqa: BLE001
        logger.exception("report_pdf: page render failed")
        return []


@dataclass(slots=True)
class PdfEmbeddedImage:
    """One embedded image on a PDF page (PDF user-space bounds, y-up)."""

    page_index: int
    bounds: tuple[float, float, float, float]  # x0, y0, x1, y1 PDF user space
    pil_image: Image.Image


@dataclass(slots=True)
class PdfPageLayout:
    """Native text + geometry for one PDF page (char indices align with ``text``)."""

    page_index: int
    width: float
    height: float
    text: str
    # Parallel to text characters: PDF user-space boxes (x0, y0, x1, y1), y-up.
    char_boxes: list[tuple[float, float, float, float]]
    images: list[PdfEmbeddedImage] = field(default_factory=list)

    def pdf_rect_to_topleft(
        self, rect: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        """Convert PDF user-space (y-up) rect to top-left origin page space."""
        x0, y0, x1, y1 = rect
        top = self.height - max(y0, y1)
        bottom = self.height - min(y0, y1)
        return min(x0, x1), top, max(x0, x1), bottom


def extract_pdf_layout(data: bytes) -> list[PdfPageLayout]:
    """Extract per-page char text/boxes via pypdfium2 (text layer only; no embedded images)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover
        logger.warning("report_pdf: pypdfium2 not installed; layout extract skipped")
        return []
    try:
        doc = pdfium.PdfDocument(data)
    except Exception:  # noqa: BLE001
        logger.exception("report_pdf: open for layout failed")
        return []

    pages: list[PdfPageLayout] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        width, height = page.get_size()
        text_page = page.get_textpage()
        n = text_page.count_chars()
        chars: list[str] = []
        boxes: list[tuple[float, float, float, float]] = []
        for i in range(n):
            ch = text_page.get_text_range(i, 1) or ""
            # Normalize CR to LF so NER offsets stay stable.
            if ch == "\r":
                ch = "\n"
            box = text_page.get_charbox(i)
            chars.append(ch)
            boxes.append((float(box[0]), float(box[1]), float(box[2]), float(box[3])))
        pages.append(
            PdfPageLayout(
                page_index=page_index,
                width=float(width),
                height=float(height),
                text="".join(chars),
                char_boxes=boxes,
                images=[],
            )
        )
    return pages


def rects_for_span(
    layout: PdfPageLayout,
    start: int,
    end: int,
    *,
    top_left: bool = True,
) -> list[tuple[float, float, float, float]]:
    """Union char boxes for ``text[start:end]`` into one rect per visual line."""
    if start < 0 or end > len(layout.char_boxes) or start >= end:
        return []
    lines: list[list[tuple[float, float, float, float]]] = []
    current: list[tuple[float, float, float, float]] = []
    prev_mid_y: float | None = None
    for i in range(start, end):
        box = layout.char_boxes[i]
        mid_y = (box[1] + box[3]) / 2.0
        if prev_mid_y is not None and abs(mid_y - prev_mid_y) > 4.0 and current:
            lines.append(current)
            current = []
        current.append(box)
        prev_mid_y = mid_y
    if current:
        lines.append(current)

    out: list[tuple[float, float, float, float]] = []
    for group in lines:
        x0 = min(b[0] for b in group)
        y0 = min(b[1] for b in group)
        x1 = max(b[2] for b in group)
        y1 = max(b[3] for b in group)
        if abs(x1 - x0) < 0.5 or abs(y1 - y0) < 0.5:
            continue
        rect = (x0, y0, x1, y1)
        out.append(layout.pdf_rect_to_topleft(rect) if top_left else rect)
    return out


def estimate_page_background(pil: Image.Image, *, border_frac: float = 0.04) -> tuple[int, int, int]:
    """Median RGB of a border ring; fallback white."""
    w, h = pil.size
    bw = max(1, int(w * border_frac))
    bh = max(1, int(h * border_frac))
    rgb = pil.convert("RGB")
    # Sample four border strips.
    strips = [
        rgb.crop((0, 0, w, bh)),
        rgb.crop((0, h - bh, w, h)),
        rgb.crop((0, bh, bw, h - bh)),
        rgb.crop((w - bw, bh, w, h - bh)),
    ]
    pixels: list[tuple[int, int, int]] = []
    for strip in strips:
        pixels.extend(list(strip.get_flattened_data()) if hasattr(strip, "get_flattened_data") else list(strip.getdata()))
    if not pixels:
        return (255, 255, 255)
    # Prefer near-white paper pixels (letterheads often put colour in the header band).
    near_white = [p for p in pixels if min(p) >= 200]
    use = near_white or [p for p in pixels if sum(p) / 3 > 180] or pixels
    rs = sorted(p[0] for p in use)
    gs = sorted(p[1] for p in use)
    bs = sorted(p[2] for p in use)
    mid = len(use) // 2
    return (rs[mid], gs[mid], bs[mid])


def fill_rects_with_color(
    pil: Image.Image,
    rects: list[tuple[int, int, int, int]],
    color: tuple[int, int, int],
) -> Image.Image:
    """Fill axis-aligned rects (top-left origin, pixel space) with ``color``."""
    from PIL import ImageDraw

    out = pil.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for x0, y0, x1, y1 in rects:
        a, b = max(0, min(x0, x1)), max(0, min(y0, y1))
        c, d = min(w, max(x0, x1)), min(h, max(y0, y1))
        if a < c and b < d:
            draw.rectangle([a, b, c, d], fill=color)
    return out


def render_redacted_pdf(
    data: bytes,
    page_rects: list[list[tuple[float, float, float, float]]],
    *,
    scale: float = 2.0,
) -> bytes:
    """
    Rasterize each page, fill ``page_rects`` (top-left page space at PDF user units)
    with estimated page background, return a new multi-page image PDF.
    """
    pages = render_pdf_pages(data, scale=scale)
    if not pages:
        return data
    layouts = extract_pdf_layout(data)
    out_pages: list[Image.Image] = []
    for i, pil in enumerate(pages):
        bg = estimate_page_background(pil)
        layout = layouts[i] if i < len(layouts) else None
        page_w = layout.width if layout else pil.width / scale
        # Map PDF top-left user units → raster pixels.
        sx = pil.width / max(page_w, 1.0)
        sy = pil.height / max((layout.height if layout else pil.height / scale), 1.0)
        rects_px: list[tuple[int, int, int, int]] = []
        for rect in page_rects[i] if i < len(page_rects) else []:
            x0, y0, x1, y1 = rect
            rects_px.append(
                (
                    int(round(x0 * sx)),
                    int(round(y0 * sy)),
                    int(round(x1 * sx)),
                    int(round(y1 * sy)),
                )
            )
        out_pages.append(fill_rects_with_color(pil, rects_px, bg))

    buf = io.BytesIO()
    if len(out_pages) == 1:
        out_pages[0].save(buf, format="PDF", resolution=150.0)
    else:
        first, rest = out_pages[0], out_pages[1:]
        first.save(buf, format="PDF", resolution=150.0, save_all=True, append_images=rest)
    return buf.getvalue()


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        while len(paragraph) > _CHARS_PER_LINE:
            cut = paragraph.rfind(" ", 0, _CHARS_PER_LINE)
            if cut < _CHARS_PER_LINE // 2:
                cut = _CHARS_PER_LINE
            lines.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        lines.append(paragraph)
    return lines or [""]


def render_plain_text_pdf(text: str) -> bytes:
    """Build a minimal single-font PDF from ``text`` (de-id rewrite; layout is not preserved)."""
    lines = _wrap_lines(text)
    pages: list[list[str]] = []
    for i in range(0, max(len(lines), 1), _LINES_PER_PAGE):
        pages.append(lines[i : i + _LINES_PER_PAGE])

    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_ids: list[int] = []
    for page_lines in pages:
        y = _PAGE_HEIGHT - _MARGIN
        content_parts = [f"BT /F1 {_FONT_SIZE} Tf {_MARGIN} {y} Td"]
        first = True
        for line in page_lines:
            if not first:
                content_parts.append(f"0 -{_LINE_HEIGHT} Td")
            first = False
            # PDF strings are Latin-1; drop characters that cannot round-trip.
            safe = _pdf_escape(line.encode("latin-1", errors="replace").decode("latin-1"))
            content_parts.append(f"({safe}) Tj")
        content_parts.append("ET")
        stream = "\n".join(content_parts).encode("latin-1")
        content_id = add_obj(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
        page_id = add_obj(
            (
                f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add_obj(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"))
    # Patch Parent refs on page objects (placeholder 0 0 R → real pages_id).
    parent_pat = re.compile(rb"/Parent 0 0 R")
    for pid in page_ids:
        objects[pid - 1] = parent_pat.sub(f"/Parent {pages_id} 0 R".encode("ascii"), objects[pid - 1])
    catalog_id = add_obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def load_pdf_slots(series_path: Path) -> list[TextSlot]:
    """Editable slots (one per PDF instance with extractable text)."""
    return load_pdf_document(series_path).slots


@dataclass(slots=True)
class PdfDocument:
    """Encapsulated PDF series for Report Text Review (rewrite replaces the PDF with plain text)."""

    series_path: Path
    datasets: dict[Path, Dataset] = field(default_factory=dict)
    slots: list[TextSlot] = field(default_factory=list)
    dirty: set[Path] = field(default_factory=set)
    _slot_paths: dict[str, Path] = field(default_factory=dict)
    _slot_text: dict[str, str] = field(default_factory=dict)
    _slot_pdf_bytes: dict[str, bytes] = field(default_factory=dict)

    def path_for(self, slot: TextSlot) -> Path:
        return self._slot_paths[slot.key]

    def pdf_bytes_for(self, slot_key: str) -> bytes | None:
        """Original encapsulated PDF bytes for page display (pre-rewrite)."""
        return self._slot_pdf_bytes.get(slot_key)

    def mark_changed(self, scans) -> None:  # noqa: ANN001
        for scan in scans:
            if scan.entities:
                self.dirty.add(self.path_for(scan.slot))

    def save(self) -> list[Path]:
        saved: list[Path] = []
        for path in sorted(self.dirty):
            ds = self.datasets[path]
            # Prefer the latest slot text for this instance (one slot per file).
            texts = [self._slot_text[k] for k, p in self._slot_paths.items() if p == path and k in self._slot_text]
            body = texts[-1] if texts else extract_pdf_text(ds)
            pdf_bytes = render_plain_text_pdf(body)
            if len(pdf_bytes) % 2:
                pdf_bytes += b"\x00"
            ds.EncapsulatedDocument = pdf_bytes
            ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
            ds.save_as(path)
            for key, p in self._slot_paths.items():
                if p == path:
                    self._slot_pdf_bytes[key] = pdf_bytes.rstrip(b"\x00")
            saved.append(path)
        self.dirty.clear()
        return saved


def load_pdf_document(series_path: Path) -> PdfDocument:
    """Load Encapsulated PDF text slots with write-back for de-id Save."""
    doc = PdfDocument(series_path=Path(series_path))
    for dcm_path in sorted(get_dcm_files(series_path)):
        try:
            ds = dcmread(dcm_path)
        except (InvalidDicomError, OSError):
            continue
        raw_pdf = encapsulated_pdf_bytes(ds)
        text = extract_pdf_text(ds)
        if not text and not raw_pdf:
            continue
        key = f"{dcm_path.name}#pdf"
        doc.datasets[dcm_path] = ds
        doc._slot_paths[key] = dcm_path
        doc._slot_text[key] = text
        if raw_pdf:
            doc._slot_pdf_bytes[key] = raw_pdf

        def _write(new: str, _key: str = key, _doc: PdfDocument = doc) -> None:
            _doc._slot_text[_key] = new
            slot = next(s for s in _doc.slots if s.key == _key)
            slot.text = new

        doc.slots.append(TextSlot(key=key, context="PDF", text=text, write=_write))
    return doc
