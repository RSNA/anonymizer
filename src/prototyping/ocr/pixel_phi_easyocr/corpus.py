"""Load MIDI-B pixel_phi manifest cases (all gold burned-in boxes)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST = Path("/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/manifest.json")
_BOX_WRAPPER = re.compile(r"^<(.*)>$", re.DOTALL)


@dataclass(frozen=True)
class GoldBox:
    """One MIDI-B pixels_hidden gold region."""

    text: str
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]

    @property
    def norm_text(self) -> str:
        """Uppercased first line (multi-line overlays keep line 1 for matching)."""
        return (self.text or "").strip().splitlines()[0].strip().upper()


@dataclass(frozen=True)
class PixelPhiCase:
    """One pixel_phi instance with gold boxes."""

    split: str
    patient_id: str
    modality: str
    dcm_path: Path
    boxes: tuple[GoldBox, ...]

    @property
    def case_id(self) -> str:
        """Stable id for logs."""
        return f"{self.split}/{self.patient_id}"


def _parse_box_payload(raw: Any) -> GoldBox | None:
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        s = raw.strip()
        m = _BOX_WRAPPER.match(s)
        if m:
            s = m.group(1)
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            logger.warning("Unparseable gold box: %s", raw[:120])
            return None
    else:
        return None
    text = str(data.get("text") or "")
    tl = data.get("top_left") or [0, 0]
    br = data.get("bottom_right") or [0, 0]
    return GoldBox(
        text=text,
        top_left=(int(tl[0]), int(tl[1])),
        bottom_right=(int(br[0]), int(br[1])),
    )


def load_pixel_phi_cases(
    manifest_path: Path | None = None,
    *,
    splits: tuple[str, ...] = ("validation", "test"),
) -> list[PixelPhiCase]:
    """
    Load every pixel_phi case that has a readable dest DICOM.

    Args:
        manifest_path: pixel_phi/manifest.json path.
        splits: Which manifest keys to include.

    Returns:
        Cases in manifest order.
    """
    path = manifest_path or _DEFAULT_MANIFEST
    doc = json.loads(path.read_text(encoding="utf-8"))
    cases: list[PixelPhiCase] = []
    for split in splits:
        for row in doc.get(split) or []:
            dest = Path(str(row.get("dest") or ""))
            if not dest.is_file():
                logger.warning("Missing DICOM for %s: %s", row.get("patient_id"), dest)
                continue
            boxes = tuple(
                b for raw in (row.get("boxes") or []) if (b := _parse_box_payload(raw)) is not None
            )
            if not boxes:
                logger.warning("No gold boxes for %s", row.get("patient_id"))
                continue
            cases.append(
                PixelPhiCase(
                    split=split,
                    patient_id=str(row.get("patient_id") or dest.parent.name),
                    modality=str(row.get("modality") or ""),
                    dcm_path=dest,
                    boxes=boxes,
                )
            )
    return cases
