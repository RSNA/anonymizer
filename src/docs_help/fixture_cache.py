"""Persistent capture caches so help shots do not re-run TotalSegmentator or EasyOCR.

TotalSegmentator: copy ``0_TS_SEG/`` into the imported series (same reuse path as
the live Harmonize UI). Pixel PHI: apply committed EasyOCR boxes through Series
View's normal overlay/whitelist/exclude filters.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from anonymizer.controller.series_overlay import OCRText

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_WORK = REPO_ROOT / "docs" / ".capture_work"
TSEG_CACHE_ROOT = CAPTURE_WORK / "fixture_cache"
OCR_CACHE_DIR = Path(__file__).resolve().parent / "ocr_cache"
TSEG_DIRNAME = "0_TS_SEG"


def tseg_cache_source(fixture: str) -> Path:
    return TSEG_CACHE_ROOT / fixture / TSEG_DIRNAME


def tseg_anatomy_cache_ready(series_path: Path) -> bool:
    seg_dir = Path(series_path) / TSEG_DIRNAME / "seg"
    return seg_dir.is_dir() and any(seg_dir.glob("*.nii.gz"))


def seed_tseg_cache(series_path: Path, fixture: str) -> bool:
    """Copy a previously saved ``0_TS_SEG`` onto an imported series. Returns True if present."""
    series_path = Path(series_path)
    dest = series_path / TSEG_DIRNAME
    src = tseg_cache_source(fixture)
    src_n = _seg_mask_count(src)
    dest_n = _seg_mask_count(dest)
    if dest_n >= src_n and dest_n > 0:
        return True
    if src_n == 0:
        return dest_n > 0
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    logger.info("Seeded TS cache for %s from %s (%d masks)", fixture, src, src_n)
    return tseg_anatomy_cache_ready(series_path)


def _seg_mask_count(ts_dir: Path) -> int:
    seg = ts_dir / "seg" if ts_dir.name == TSEG_DIRNAME else ts_dir / TSEG_DIRNAME / "seg"
    if not seg.is_dir():
        return 0
    return sum(1 for _ in seg.glob("*.nii.gz"))


def harvest_tseg_cache_from_tree(root: Path, fixture: str = "CT_Head_With_Contrast") -> bool:
    """Keep a leftover ``0_TS_SEG`` from a previous capture work dir before it is wiped."""
    dest = tseg_cache_source(fixture)
    dest_n = _seg_mask_count(dest)
    if not root.is_dir():
        return dest_n > 0
    best: Path | None = None
    best_masks = 0
    for cache_dir in root.rglob(TSEG_DIRNAME):
        masks = _seg_mask_count(cache_dir)
        if masks > best_masks:
            best_masks = masks
            best = cache_dir
    if best is None or best_masks <= dest_n:
        return dest_n > 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(best, dest)
    logger.info("Harvested TS cache for %s from %s (%d masks)", fixture, best, best_masks)
    return True


def save_tseg_cache(series_path: Path, fixture: str) -> bool:
    """Persist ``0_TS_SEG`` so later capture runs skip TotalSegmentator."""
    series_path = Path(series_path)
    src = series_path / TSEG_DIRNAME
    if not tseg_anatomy_cache_ready(series_path):
        return False
    dest = tseg_cache_source(fixture)
    src_n = _seg_mask_count(src)
    dest_n = _seg_mask_count(dest)
    if dest_n >= src_n and dest_n > 0:
        logger.info("Keeping existing TS cache for %s (%d masks ≥ %d)", fixture, dest_n, src_n)
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    logger.info("Saved TS cache for %s → %s (%d masks)", fixture, dest, src_n)
    return True


def ocr_cache_path(fixture: str) -> Path:
    return OCR_CACHE_DIR / f"{fixture}.json"


def load_ocr_cache(fixture: str) -> dict[int, list[OCRText]]:
    path = ocr_cache_path(fixture)
    if not path.is_file():
        raise RuntimeError(f"No pixel-PHI detection cache for fixture {fixture!r} ({path})")
    payload = json.loads(path.read_text(encoding="utf-8"))
    frames = payload.get("frames") or {}
    out: dict[int, list[OCRText]] = {}
    for key, items in frames.items():
        texts: list[OCRText] = []
        for item in items:
            box = item["box"]
            texts.append(
                OCRText(
                    text=str(item["text"]),
                    top_left=(int(box[0]), int(box[1])),
                    bottom_right=(int(box[2]), int(box[3])),
                    prob=float(item.get("prob", 0.99)),
                )
            )
        out[int(key)] = texts
    if not out:
        raise RuntimeError(f"Pixel-PHI detection cache for {fixture!r} has no frames")
    return out


def cached_pixel_phi_labels(fixture: str) -> list[str]:
    """Deduped detection strings for Patient Lookup metadata (no EasyOCR)."""
    seen: set[str] = set()
    labels: list[str] = []
    for texts in load_ocr_cache(fixture).values():
        for item in texts:
            label = item.text.strip()
            if label and label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


def apply_cached_ocr_detections(view: Any, fixture: str) -> int:
    """Install cached Detect Text overlays using Series View's own draw/filter path."""
    from anonymizer.utils.translate import _

    result = load_ocr_cache(fixture)
    apply = getattr(view, "_apply_ocr_detections_result", None)
    if not callable(apply):
        raise RuntimeError("Series View is missing _apply_ocr_detections_result")
    apply(result)
    detection_count = sum(len(texts) for texts in result.values())
    status = _("Text detection complete") + f": {detection_count} " + _("detections")
    if hasattr(view, "update_status"):
        view.update_status(status, debug_log=True)
    if hasattr(view, "_refresh_ocr_toolbar_buttons"):
        view._refresh_ocr_toolbar_buttons()
    viewer = getattr(view, "image_viewer", None)
    if viewer is not None and hasattr(viewer, "refresh_current_image"):
        viewer.refresh_current_image()
    logger.info("Applied cached pixel-PHI detections for %s (%d boxes)", fixture, detection_count)
    return detection_count
