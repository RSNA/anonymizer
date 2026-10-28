"""Persistent capture caches for TotalSegmentator (not EasyOCR).

TotalSegmentator: copy ``0_TS_SEG/`` into the imported series (same reuse path as
the live Harmonize UI). Pixel PHI help shots run Series View **Detect** live —
box coordinates are never committed.

Public API
----------
tseg_cache_source(fixture: str) -> Path
    Directory of the saved ``0_TS_SEG`` tree for a fixture.

tseg_anatomy_cache_ready(series_path: Path) -> bool
    True when the series already has TotalSegmentator anatomy masks.

clear_series_tseg_dir(series_path: Path) -> bool
    Remove ``0_TS_SEG`` under a series (orphan CT masks spoil CXR Pixel PHI shots).

seed_tseg_cache(series_path: Path, fixture: str) -> bool
    Copy a previously saved ``0_TS_SEG`` onto an imported series.

harvest_tseg_cache_from_tree(root: Path, fixture: str = "CT_Head_With_Contrast") -> bool
    Keep a leftover ``0_TS_SEG`` from a previous capture work dir.

save_tseg_cache(series_path: Path, fixture: str) -> bool
    Persist ``0_TS_SEG`` so later capture runs skip TotalSegmentator.

pixel_phi_lookup_labels(fixture: str) -> list[str]
    Burned-in text strings for Patient Lookup CSV seeding (not Detect boxes).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_WORK = REPO_ROOT / "docs" / ".capture_work"
TSEG_CACHE_ROOT = CAPTURE_WORK / "fixture_cache"
TSEG_DIRNAME = "0_TS_SEG"

# Dataset Embedded PHI column seeding for Patient Lookup shots — text only, not boxes.
_PIXEL_PHI_LOOKUP_LABELS: dict[str, tuple[str, ...]] = {
    "davidson_cxr": (
        "DAVIDSON",
        "DOUGLAS [M]",
        "01.09.2012",
        "DOB: 06.16.1976",
        "Semi-Upright",
        "Portable",
    ),
    "us_rgb_single_frame": (
        "mindray",
        "26,05/2018",
        "A-Abdomen",
        "LIVER",
        "Dist",
        "15.23",
    ),
}


def tseg_cache_source(fixture: str) -> Path:
    return TSEG_CACHE_ROOT / fixture / TSEG_DIRNAME


def tseg_anatomy_cache_ready(series_path: Path) -> bool:
    seg_dir = Path(series_path) / TSEG_DIRNAME / "seg"
    return seg_dir.is_dir() and any(seg_dir.glob("*.nii.gz"))


def clear_series_tseg_dir(series_path: Path) -> bool:
    """Remove ``0_TS_SEG`` under a series (wrong leftover masks spoil Pixel PHI shots)."""
    series_path = Path(series_path)
    dest = series_path / TSEG_DIRNAME
    if not dest.exists():
        return False
    shutil.rmtree(dest)
    logger.info("Cleared stray TS cache under %s", series_path)
    return True


def seed_tseg_cache(series_path: Path, fixture: str) -> bool:
    """Copy a previously saved ``0_TS_SEG`` onto an imported series. Returns True if present."""
    series_path = Path(series_path)
    dest = series_path / TSEG_DIRNAME
    src = tseg_cache_source(fixture)
    src_n = _seg_mask_count(src)
    dest_n = _seg_mask_count(dest)
    # Fixtures without a committed cache must not keep orphan masks (e.g. CT
    # brain chips left under davidson_cxr from an earlier capture project).
    if src_n == 0:
        if dest_n > 0:
            clear_series_tseg_dir(series_path)
        return False
    if dest_n >= src_n and dest_n > 0:
        return True
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


def pixel_phi_lookup_labels(fixture: str) -> list[str]:
    """Burned-in text strings for Patient Lookup CSV seeding (not Detect boxes)."""
    return list(_PIXEL_PHI_LOOKUP_LABELS.get(fixture, ()))
