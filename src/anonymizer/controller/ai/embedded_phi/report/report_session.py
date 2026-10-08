"""Non-UI state for Report Text Review: load → detect → exclude/zones → remove → save."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import (
    SlotScan,
    entity_counts,
    removed_texts,
)
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import PhiEntity
from anonymizer.controller.ai.embedded_phi.ner.replace import ReplaceMode, apply_scans
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import filter_ocr_outside_exclude_rects, rects_intersect
from anonymizer.controller.ai.embedded_phi.report.content_text import TextSlot
from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import (
    PdfDocument,
    PdfPageLayout,
    load_pdf_document,
    render_redacted_pdf,
)
from anonymizer.controller.ai.embedded_phi.report.hits import ReportHit
from anonymizer.controller.ai.embedded_phi.report.report_from_ocr import deid_transcript_lines, write_ocr_report_sr
from anonymizer.controller.ai.embedded_phi.report.report_ner import analyze_report_text
from anonymizer.controller.ai.embedded_phi.report.report_sr import SrDocument, load_sr_document
from anonymizer.controller.series_overlay import OCRText, UserRectangle
from anonymizer.model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)

DocumentKind = Literal["sr", "pdf", "pixel_report"]


def _hit_as_ocr(hit: ReportHit) -> OCRText:
    x0, y0, x1, y1 = hit.as_pixel_rect()
    return OCRText(text=hit.text, top_left=(x0, y0), bottom_right=(x1, y1), prob=1.0, phi_label=hit.label)


def filter_hits_outside_exclude(
    hits: list[ReportHit],
    exclude_rects: list[UserRectangle] | None,
) -> list[ReportHit]:
    if not exclude_rects:
        return list(hits)
    kept: list[ReportHit] = []
    for hit in hits:
        ocr = _hit_as_ocr(hit)
        if any(rects_intersect(ocr, rect) for rect in exclude_rects):
            continue
        kept.append(hit)
    return kept


class ReportSession:
    """One open report series (SR, Encapsulated PDF, or SC pixel report)."""

    def __init__(self, series_path: Path, document_kind: DocumentKind = "sr", *, locale: str = "en_US") -> None:
        self.series_path = Path(series_path)
        self.document_kind: DocumentKind = document_kind
        self.locale = locale
        self._sr: SrDocument | None = None
        self._pdf: PdfDocument | None = None
        self._layouts: list[PdfPageLayout] = []
        self.hits: list[ReportHit] = []
        self.excluded_hit_keys: set[str] = set()
        self.exclude_rects: list[UserRectangle] = []
        self.blackout_rects: list[UserRectangle] = []
        self.pending_draw_rects: list[UserRectangle] = []
        self._transcript_by_page: dict[int, list[str]] = {}
        self._removed_phi_texts: list[str] = []
        self._removed_by_path: dict[Path, list[str]] = {}
        self._paint_rects_by_page: list[list[tuple[float, float, float, float]]] | None = None
        self._deid_mode: ReplaceMode = "blank"
        self._deid_synth: SyntheticPhiFactory | None = None
        self.removed_since_save = False
        self._pdf_dirty = False

        if document_kind == "sr":
            self._sr = load_sr_document(self.series_path)
            self.slots: list[TextSlot] = self._sr.slots
        elif document_kind == "pdf":
            self._pdf = load_pdf_document(self.series_path)
            self.slots = self._pdf.slots
        else:
            # pixel_report: slots filled after OCR detect (transcript lines)
            self.slots = []
        self.scans: list[SlotScan] = []
        self.excluded: set[tuple[str, int]] = set()  # SR text-canvas exclude (slot_key, start)

    @property
    def can_edit(self) -> bool:
        return self._sr is not None or self._pdf is not None or self.document_kind == "pixel_report"

    @property
    def dirty(self) -> bool:
        if self._sr is not None:
            return bool(self._sr.dirty)
        if self._pdf is not None:
            return bool(self._pdf.dirty) or self._pdf_dirty
        return self._pdf_dirty or self.removed_since_save

    def pdf_bytes(self) -> bytes | None:
        if self._pdf is None or not self.slots:
            return None
        return self._pdf.pdf_bytes_for(self.slots[0].key)

    def _ocr_reader(self):
        from easyocr import Reader

        from anonymizer.controller.ai.embedded_phi.pixel.cache import OCR_LANGS, OCR_MODEL_DIR

        return Reader(lang_list=list(OCR_LANGS), model_storage_directory=str(OCR_MODEL_DIR), verbose=False)

    def detect(
        self,
        *,
        ocr_reader=None,
        progress=None,
    ) -> list[ReportHit] | list[SlotScan]:
        """Detect PHI. PDF/pixel_report → ``hits``; SR → ``scans``.

        ``progress`` is an optional ``Callable[[str], None]`` for UI status phases.
        """
        self.excluded_hit_keys.clear()
        self.excluded.clear()
        self.hits = []
        self.scans = []
        self._transcript_by_page.clear()

        if self.document_kind == "sr":
            if progress is not None:
                from anonymizer.utils.translate import _

                progress(_("Detecting PHI in text (NER)…"))
            self.scans = [
                SlotScan(
                    slot,
                    analyze_report_text(
                        slot.text, locale=self.locale, unit=f"slot={slot.key}"
                    ),
                )
                for slot in self.slots
                if slot.text.strip()
            ]
            return self.scans

        if self.document_kind == "pdf":
            data = self.pdf_bytes()
            if not data:
                logger.info("report_detect: start pdf — no PDF bytes")
                return []
            from anonymizer.controller.ai.embedded_phi.report.pdf_ocr import detect_pdf_hits

            self._layouts, raw_hits = detect_pdf_hits(
                data, locale=self.locale, progress=progress
            )
            before_ex = len(raw_hits)
            self.hits = filter_hits_outside_exclude(raw_hits, self.exclude_rects)
            if len(self.exclude_rects) and len(self.hits) != before_ex:
                logger.info(
                    "report_detect: exclude zones — hits %d → %d (%d zone(s))",
                    before_ex,
                    len(self.hits),
                    len(self.exclude_rects),
                )
            for layout in self._layouts:
                if layout.text.strip():
                    self._transcript_by_page.setdefault(layout.page_index, []).append(layout.text)
            return self.hits

        # pixel_report — OCR each DICOM frame via detect_text
        return self._detect_pixel_report(ocr_reader=ocr_reader, progress=progress)

    def _detect_pixel_report(self, *, ocr_reader=None, progress=None) -> list[ReportHit]:
        import numpy as np
        from pydicom import dcmread

        from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
            REPORT_PIXEL_EASYOCR_OVERRIDES,
            annotate_ocr_phi_labels,
            detect_text,
            ocr_image_for_frame,
        )
        from anonymizer.utils.storage import get_dcm_files
        from anonymizer.utils.translate import _

        reader = ocr_reader
        if reader is None:
            try:
                from anonymizer.controller.ai.embedded_phi.pixel.cache import ocr_models_ready

                if ocr_models_ready():
                    reader = self._ocr_reader()
            except Exception:  # noqa: BLE001
                reader = None
        if reader is None:
            logger.warning("report_detect: start pixel_report — OCR reader unavailable")
            return []
        hits: list[ReportHit] = []
        paths = sorted(get_dcm_files(self.series_path))
        logger.info("report_detect: start pixel_report frames=%d locale=%s", len(paths), self.locale)
        from anonymizer.controller.ai.embedded_phi.report.hits import hit_key
        from anonymizer.controller.ai.embedded_phi.report.pdf_ocr import _hit_label_summary

        for page_index, dcm_path in enumerate(paths):
            page_no = page_index + 1
            if progress is not None:
                progress(
                    _("Scanning page image (OCR)…") + f" — {_('page')} {page_no}/{len(paths)}"
                )
            try:
                ds = dcmread(dcm_path)
                pixels = ds.pixel_array
            except Exception:  # noqa: BLE001
                logger.info("report_detect: [1] frame %d — skip (unreadable)", page_no)
                continue
            frame = pixels[0] if pixels.ndim == 3 and pixels.shape[-1] not in (3, 4) else pixels
            try:
                bgr = ocr_image_for_frame(ds, frame if isinstance(frame, np.ndarray) else np.asarray(frame))
            except Exception:  # noqa: BLE001
                logger.exception("report_detect: frame %d OCR prep failed", page_no)
                continue
            logger.info("report_detect: [1] OCR frame %d/%d", page_no, len(paths))
            raw = detect_text(
                bgr,
                reader,
                apply_noise_filter=False,
                annotate_phi_labels=False,
                modality=str(getattr(ds, "Modality", "SC") or "SC"),
                log_steps=False,
                easyocr_overrides=REPORT_PIXEL_EASYOCR_OVERRIDES,
            )
            tokens = len(raw or [])
            logger.info("report_detect: [1] OCR frame %d → tokens=%d", page_no, tokens)
            if not raw:
                continue
            logger.info("report_detect: [2] NER frame %d", page_no)
            labeled = annotate_ocr_phi_labels(raw, locale=self.locale)
            labeled = filter_ocr_outside_exclude_rects(labeled, self.exclude_rects)
            page_hits: list[ReportHit] = []
            for item in labeled:
                label = (item.phi_label or "").strip()
                if not label:
                    if item.text.strip():
                        self._transcript_by_page.setdefault(page_index, []).append(item.text)
                    continue
                x0, y0, x1, y1 = item.get_bounding_box()
                text = (item.text or "").strip()
                hit = ReportHit(
                    page_index=page_index,
                    text=text,
                    label=label,
                    rect=(float(x0), float(y0), float(x1), float(y1)),
                    source="ocr",
                    key=hit_key(page_index, "ocr", x0, y1, text),
                )
                logger.info(
                    "report_detect: PHI pixel_hit label=%s text=%r rect=%s",
                    hit.label,
                    hit.text,
                    hit.rect,
                )
                page_hits.append(hit)
                if text:
                    self._transcript_by_page.setdefault(page_index, []).append(text)
            logger.info(
                "report_detect: [2] NER frame %d → hits=%d (%s)",
                page_no,
                len(page_hits),
                _hit_label_summary(page_hits),
            )
            hits.extend(page_hits)
        self.hits = hits
        logger.info(
            "report_detect: done pixel_report — total_hits=%d (%s)",
            len(hits),
            _hit_label_summary(hits),
        )
        return hits

    def toggle_excluded(self, slot_key: str, start: int) -> bool:
        """SR text-canvas exclude flip."""
        ident = (slot_key, start)
        if ident in self.excluded:
            self.excluded.discard(ident)
            return False
        self.excluded.add(ident)
        return True

    def toggle_hit_excluded(self, key: str) -> bool:
        if key in self.excluded_hit_keys:
            self.excluded_hit_keys.discard(key)
            return False
        self.excluded_hit_keys.add(key)
        return True

    def is_excluded(self, slot_key: str, entity: PhiEntity) -> bool:
        return (slot_key, entity.start) in self.excluded

    def active_hits(self) -> list[ReportHit]:
        return [h for h in self.hits if h.key not in self.excluded_hit_keys]

    def active_scans(self) -> list[SlotScan]:
        out: list[SlotScan] = []
        for scan in self.scans:
            kept = [e for e in scan.entities if not self.is_excluded(scan.slot.key, e)]
            if kept:
                out.append(SlotScan(scan.slot, kept))
        return out

    def counts(self) -> dict[str, int]:
        if self.document_kind == "sr":
            return entity_counts(self.active_scans())
        counts: dict[str, int] = {}
        for hit in self.active_hits():
            counts[hit.label] = counts.get(hit.label, 0) + 1
        return counts

    def commit_blackout_pending(self) -> int:
        n = len(self.pending_draw_rects)
        self.blackout_rects.extend(self.pending_draw_rects)
        self.pending_draw_rects.clear()
        if n:
            self._pdf_dirty = True
        return n

    def commit_exclude_pending(self) -> int:
        n = len(self.pending_draw_rects)
        self.exclude_rects.extend(self.pending_draw_rects)
        self.pending_draw_rects.clear()
        return n

    def remove_exclude_rect_at(self, x: int, y: int) -> bool:
        for i, rect in enumerate(self.exclude_rects):
            x0, y0, x1, y1 = rect.get_bounding_box()
            if min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1):
                del self.exclude_rects[i]
                return True
        return False

    def _path_for(self, slot: TextSlot) -> Path:
        if self._sr is not None:
            return self._sr.path_for(slot)
        assert self._pdf is not None
        return self._pdf.path_for(slot)

    def _patient_id(self) -> str:
        datasets = (self._sr.datasets if self._sr is not None else None) or (
            self._pdf.datasets if self._pdf is not None else {}
        )
        if not datasets:
            return "ANON0000"
        return str(next(iter(datasets.values())).get("PatientID", "ANON0000"))

    def remove(
        self,
        mode: ReplaceMode = "blank",
        *,
        project_id: str = "default",
        anon_ptid: str | None = None,
    ) -> int:
        """Apply remove: SR text replace; PDF/pixel capture originals and mark dirty for Save paint-out."""
        if not self.can_edit:
            raise RuntimeError("Report is not editable")

        synth = None
        if mode == "synth":
            synth = SyntheticPhiFactory(
                project_id=project_id,
                anon_ptid=anon_ptid or self._patient_id(),
                locale=self.locale,
            )

        if self.document_kind == "sr":
            scans = self.active_scans()
            if not scans:
                return 0
            for scan in scans:
                path = self._path_for(scan.slot)
                bucket = self._removed_by_path_bucket(path)
                bucket.extend(t for t in removed_texts([scan]) if t not in bucket)
            changed = apply_scans(scans, mode=mode, synth=synth, locale=self.locale)
            if self._sr is not None:
                self._sr.mark_changed(scans)
            self.removed_since_save = True
            self.scans = []
            self.excluded.clear()
            return changed

        active = self.active_hits()
        originals = [h.text for h in active if h.text.strip()]
        for t in originals:
            if t not in self._removed_phi_texts:
                self._removed_phi_texts.append(t)
        self.stash_paint_rects_before_clear()
        # Text arm: de-id transcript in memory for sibling SR on Save
        self._deid_mode = mode
        self._deid_synth = synth
        self.removed_since_save = True
        self._pdf_dirty = True
        # Clear hit overlays after remove (Series View clears OCR after remove)
        n = len(active) + len(self.blackout_rects)
        self.hits = []
        self.excluded_hit_keys.clear()
        return max(n, 1 if self.blackout_rects or originals else 0)

    def _removed_by_path_bucket(self, path: Path) -> list[str]:
        return self._removed_by_path.setdefault(path, [])

    def _promote_transcript_sr(self) -> Path | None:
        if not self._transcript_by_page:
            return None
        mode: ReplaceMode = getattr(self, "_deid_mode", "blank")
        synth = getattr(self, "_deid_synth", None)
        lines = deid_transcript_lines(
            self._transcript_by_page,
            mode=mode,
            synth=synth,
            locale=self.locale,
        )
        if not lines:
            return None
        return write_ocr_report_sr(self.series_path, lines)

    def save(self, anon_model: AnonymizerModel | None = None) -> list[Path]:
        """Write redacted source + Dataset PHI capture + sibling Basic Text SR."""
        saved: list[Path] = []

        if self.document_kind == "sr":
            doc = self._sr
            if doc is None:
                return []
            saved = doc.save()
            if anon_model is not None and self.removed_since_save:
                series_uid: str | None = None
                for path, texts in getattr(self, "_removed_by_path", {}).items():
                    ds = doc.datasets[path]
                    series_uid = str(ds.get("SeriesInstanceUID", "")) or series_uid
                    anon_model.set_instance_embedded_phi(str(ds.SOPInstanceUID), texts)
                if series_uid:
                    anon_model.set_series_embedded_phi_scanned(series_uid, scanned=True)
            getattr(self, "_removed_by_path", {}).clear()
            self.removed_since_save = False
            return saved

        if self.document_kind == "pdf" and self._pdf is not None:
            data = self.pdf_bytes()
            if data and (self._pdf_dirty or self.removed_since_save):
                # Collect paint rects from last active hits we stored as originals + blackouts.
                # Re-detect geometry is gone after remove(); use blackout_rects + rebuild from
                # transcript is insufficient. Keep paint list on remove.
                page_rects = getattr(self, "_paint_rects_by_page", None)
                if page_rects is None:
                    page_rects = self._blackout_only_page_rects(data)
                redacted = render_redacted_pdf(data, page_rects)
                if len(redacted) % 2:
                    redacted += b"\x00"
                for _path, ds in self._pdf.datasets.items():
                    ds.EncapsulatedDocument = redacted
                    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
                    ds.save_as(path)
                    for key, p in self._pdf._slot_paths.items():
                        if p == path:
                            self._pdf._slot_pdf_bytes[key] = redacted.rstrip(b"\x00")
                    saved.append(path)
                self._pdf.dirty.clear()
                self._pdf_dirty = False

            if anon_model is not None and self.removed_since_save and self._removed_phi_texts:
                for _path, ds in self._pdf.datasets.items():
                    anon_model.set_instance_embedded_phi(str(ds.SOPInstanceUID), self._removed_phi_texts)
                    anon_model.set_series_embedded_phi_scanned(str(ds.SeriesInstanceUID), scanned=True)
                    break
            sr_path = self._promote_transcript_sr()
            if sr_path is not None:
                saved.append(sr_path)
            self._removed_phi_texts.clear()
            self.removed_since_save = False
            self.blackout_rects.clear()
            self._paint_rects_by_page = None
            return saved

        # pixel_report: paint frames via page-bg fill, save series frames
        if self.document_kind == "pixel_report":
            saved = self._save_pixel_report(anon_model)
        return saved

    def _blackout_only_page_rects(self, data: bytes) -> list[list[tuple[float, float, float, float]]]:
        from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import extract_pdf_layout

        layouts = extract_pdf_layout(data) or [None]
        n = max(len(layouts), 1)
        out: list[list[tuple[float, float, float, float]]] = [[] for _ in range(n)]
        for rect in self.blackout_rects:
            x0, y0, x1, y1 = rect.get_bounding_box()
            out[0].append((float(x0), float(y0), float(x1), float(y1)))
        return out

    def stash_paint_rects_before_clear(self) -> None:
        """Call from Remove before clearing hits so Save can paint PHI + blackout zones."""
        by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for hit in self.active_hits():
            by_page.setdefault(hit.page_index, []).append(hit.rect)
        for rect in self.blackout_rects:
            x0, y0, x1, y1 = rect.get_bounding_box()
            by_page.setdefault(0, []).append((float(x0), float(y0), float(x1), float(y1)))
        if by_page:
            max_page = max(by_page)
            self._paint_rects_by_page = [by_page.get(i, []) for i in range(max_page + 1)]
        else:
            self._paint_rects_by_page = None

    def preview_redacted_pdf(self) -> bytes | None:
        """Raster-redact stashed paint rects for in-memory Remove preview (does not write DICOM)."""
        if self.document_kind != "pdf":
            return None
        data = self.pdf_bytes()
        if not data:
            return None
        page_rects = getattr(self, "_paint_rects_by_page", None)
        if page_rects is None:
            if not self.blackout_rects:
                return None
            page_rects = self._blackout_only_page_rects(data)
        return render_redacted_pdf(data, page_rects)

    def _save_pixel_report(self, anon_model: AnonymizerModel | None) -> list[Path]:
        import numpy as np
        from PIL import Image
        from pydicom import dcmread

        from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import (
            estimate_page_background,
            fill_rects_with_color,
        )
        from anonymizer.utils.storage import get_dcm_files

        paint = getattr(self, "_paint_rects_by_page", None) or []
        saved: list[Path] = []
        paths = sorted(get_dcm_files(self.series_path))
        series_uid = None
        for page_index, dcm_path in enumerate(paths):
            try:
                ds = dcmread(dcm_path)
                arr = ds.pixel_array
            except Exception:  # noqa: BLE001
                continue
            frame = arr[0] if arr.ndim >= 3 and arr.shape[-1] not in (3, 4) and arr.ndim == 3 else arr
            if frame.ndim == 2:
                pil = Image.fromarray(frame).convert("RGB")
            else:
                pil = Image.fromarray(frame.astype(np.uint8)).convert("RGB")
            bg = estimate_page_background(pil)
            rects = []
            if page_index < len(paint):
                for r in paint[page_index]:
                    rects.append(tuple(int(round(v)) for v in r))  # type: ignore[arg-type]
            for rect in self.blackout_rects:
                if page_index == 0:
                    rects.append(rect.get_bounding_box())
            redacted = fill_rects_with_color(pil, rects, bg)
            # Write back simply as RGB if possible — keep existing bit depth when grayscale.
            out_arr = np.asarray(redacted.convert("L" if frame.ndim == 2 else "RGB"))
            if frame.ndim == 2:
                ds.PixelData = out_arr.astype(frame.dtype).tobytes()
            else:
                ds.PixelData = out_arr.astype(np.uint8).tobytes()
                ds.SamplesPerPixel = 3
                ds.PhotometricInterpretation = "RGB"
            ds.save_as(dcm_path)
            saved.append(dcm_path)
            series_uid = str(ds.get("SeriesInstanceUID", "")) or series_uid
            if anon_model is not None and self._removed_phi_texts:
                anon_model.set_instance_embedded_phi(str(ds.SOPInstanceUID), self._removed_phi_texts)
        if anon_model is not None and series_uid:
            anon_model.set_series_embedded_phi_scanned(series_uid, scanned=True)
        sr_path = self._promote_transcript_sr()
        if sr_path is not None:
            saved.append(sr_path)
        self._removed_phi_texts.clear()
        self.removed_since_save = False
        self._pdf_dirty = False
        self.blackout_rects.clear()
        self._paint_rects_by_page = None
        return saved
