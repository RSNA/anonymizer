"""MIDI-B dataset defaults and harness-run layout."""

from datetime import datetime, timezone
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
VENDOR_DIR = PACKAGE_DIR / "vendor"
OFFICIAL_VALIDATOR_DIR = VENDOR_DIR / "MIDI_validation_script"

DEFAULT_MIDI_B_ROOT = Path("/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B")
DEFAULT_HARNESS_RUNS = DEFAULT_MIDI_B_ROOT / "harness-runs"

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

DEFAULT_SYNTHETIC_TEST = (
    DEFAULT_MIDI_B_ROOT
    / "Synthetic Test"
    / "manifest-1740627604844"
    / "MIDI-B-Synthetic-Test"
)


def split_paths(split: str) -> tuple[Path, Path | None]:
    """
    Return synthetic DICOM root and optional answer-key DB for a split name.

    Args:
        split: validation or test (and common aliases).

    Returns:
        (synthetic_root, answer_db or None for test).

    Raises:
        ValueError: Unknown split name.
    """
    key = split.strip().lower().replace("-", "_")
    if key in ("validation", "val", "synthetic_validation"):
        return DEFAULT_SYNTHETIC_VALIDATION, DEFAULT_ANSWER_KEY_VALIDATION
    if key in ("test", "synthetic_test"):
        return DEFAULT_SYNTHETIC_TEST, None
    raise ValueError(f"unknown split {split!r}; use 'validation' or 'test'")


def new_run_dir(*, split: str, slug: str | None = None, root: Path | None = None) -> Path:
    """
    Allocate a timestamped harness-run directory.

    Args:
        split: validation or test label used in the folder name.
        slug: Optional short label appended after the UTC stamp.
        root: Parent for runs (default DEFAULT_HARNESS_RUNS).

    Returns:
        Path to the new run directory (created).
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{split}_{stamp}"
    if slug:
        name = f"{name}_{slug}"
    path = Path(root or DEFAULT_HARNESS_RUNS) / name
    path.mkdir(parents=True, exist_ok=False)
    return path
