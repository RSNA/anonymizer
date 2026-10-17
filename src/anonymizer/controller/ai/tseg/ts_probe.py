"""TotalSegmentator leaf probes: weight kinds, package/license checks, checkpoint presence (no tseg deps)."""

from __future__ import annotations

import importlib
import importlib.metadata as md
import logging
import sys
from enum import StrEnum
from pathlib import Path

from anonymizer.utils.translate import _

try:
    from totalsegmentator.config import has_valid_license_offline
except ImportError:
    has_valid_license_offline = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

TSEG_INSTALL_HINT = "pip install rsna-anonymizer"
CHECKPOINT_NAME = "checkpoint_final.pth"


class TsWeightKind(StrEnum):
    ANATOMY = "anatomy"  # CT Harmonize (total + contrast)
    ANATOMY_MR = "anatomy_mr"  # MR Harmonize (total_mr)
    FACE = "face"  # CT Face Blur
    FACE_MR = "face_mr"  # MR Face Blur
    BRAIN_STRUCTURES = "brain_structures"


def totalsegmentator_available() -> bool:
    """True when the TotalSegmentator package is installed and importable."""

    try:
        md.version("totalsegmentator")
    except md.PackageNotFoundError:
        return False

    saved_path = sys.path
    try:
        sys.path = [entry for entry in sys.path if entry not in ("", ".")]
        spec = importlib.util.find_spec("totalsegmentator")
        if spec is None or spec.loader is None:
            return False
        importlib.import_module("totalsegmentator")
    except ImportError as exc:
        logger.debug("TotalSegmentator import check failed: %s", exc)
        return False
    finally:
        sys.path = saved_path
    return True


def verify_face_license() -> tuple[bool, str]:
    if not totalsegmentator_available():
        return False, _("TotalSegmentator not installed. Install with: {hint}").format(hint=TSEG_INSTALL_HINT)
    try:
        valid, message = has_valid_license_offline()
    except Exception as exc:
        return False, _("License check failed: {error}").format(error=exc)
    if valid == "yes":
        return True, message
    return False, message


def checkpoint_ready(model_folder: Path | None) -> bool:
    """True when ``checkpoint_final.pth`` exists under the model folder (root or fold_*)."""
    if model_folder is None:
        return False
    root_checkpoint = model_folder / CHECKPOINT_NAME
    if root_checkpoint.is_file():
        return True
    fold_checkpoint = model_folder / "fold_0" / CHECKPOINT_NAME
    if fold_checkpoint.is_file():
        return True
    return any(model_folder.glob(f"fold_*/{CHECKPOINT_NAME}"))
