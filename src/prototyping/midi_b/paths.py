"""MIDI-B dataset defaults and results roots.

Results (candidates, mappings, official score) live on the external TCIA volume
so primary-disk space is not consumed across iteration runs:

  /Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/harness-runs/<split>_<UTC>[_<slug>]/
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
# Local pointer / symlink farm only (not bulk candidates).
RESULTS_DIR = PACKAGE_DIR / "results"
VENDOR_DIR = PACKAGE_DIR / "vendor"
OFFICIAL_VALIDATOR_DIR = VENDOR_DIR / "MIDI_validation_script"

DEFAULT_MIDI_B_ROOT = Path("/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B")
# Timestamped run artifacts (candidates + score) — external drive.
DEFAULT_HARNESS_RUNS = DEFAULT_MIDI_B_ROOT / "harness-runs"

# Synthetic Validation (challenge input + answer key)
DEFAULT_SYNTHETIC_VALIDATION = (
    DEFAULT_MIDI_B_ROOT
    / "Synthetic Validation"
    / "manifest-1740445452889"
    / "MIDI-B-Synthetic-Validation"
)
DEFAULT_ANSWER_KEY_VALIDATION = (
    DEFAULT_MIDI_B_ROOT
    / "Synthetic Validation"
    / "Answer Key"
    / "MIDI-B-Answer-Key-Validation.db"
)
DEFAULT_CURATED_VALIDATION = (
    DEFAULT_MIDI_B_ROOT / "Curated Validation" / "MIDI-B-Curated-Validation"
)

# Synthetic Test (no public answer key in typical challenge setup)
DEFAULT_SYNTHETIC_TEST = (
    DEFAULT_MIDI_B_ROOT
    / "Synthetic Test"
    / "manifest-1740627604844"
    / "MIDI-B-Synthetic-Test"
)
DEFAULT_CURATED_TEST = DEFAULT_MIDI_B_ROOT / "Curated Test" / "MIDI-B-Curated-Test"


def split_paths(split: str) -> tuple[Path, Path | None, Path]:
    """Return (synthetic_root, answer_db|None, curated_root) for a split name."""
    key = split.strip().lower().replace("-", "_")
    if key in ("validation", "val", "synthetic_validation"):
        return (
            DEFAULT_SYNTHETIC_VALIDATION,
            DEFAULT_ANSWER_KEY_VALIDATION,
            DEFAULT_CURATED_VALIDATION,
        )
    if key in ("test", "synthetic_test"):
        return DEFAULT_SYNTHETIC_TEST, None, DEFAULT_CURATED_TEST
    raise ValueError(f"unknown split {split!r}; use 'validation' or 'test'")


def run_dir(split: str, slug: str | None = None, *, runs_root: Path | None = None) -> Path:
    """``<runs_root>/<split>_<UTC>[_<slug>]`` on the external harness-runs volume."""
    root = Path(runs_root) if runs_root is not None else DEFAULT_HARNESS_RUNS
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{split}_{stamp}"
    if slug:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug.strip())
        if safe:
            name = f"{name}_{safe}"
    return root / name
