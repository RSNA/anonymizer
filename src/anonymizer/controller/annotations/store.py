"""Paths and IO for ``0_TS_SEG/annotations/`` label volumes."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.seg_retention import (
    read_mask_geometry,
    sitk_image_from_mask_geometry,
)

logger = logging.getLogger(__name__)

ANNOTATIONS_DIRNAME = "annotations"
LABELS_FILENAME = "labels.nii.gz"
LABEL_MAP_FILENAME = "label_map.json"
EDITS_DIRNAME = "edits"

PaintTargetKind = Literal["user", "ts_edit"]

_USER_LABEL_PALETTE_BGR: tuple[tuple[int, int, int], ...] = (
    (0, 165, 255),
    (0, 255, 128),
    (255, 128, 0),
    (255, 0, 255),
    (128, 255, 0),
    (0, 128, 255),
    (255, 255, 0),
    (180, 105, 255),
)


def annotations_dir(cache_dir: Path) -> Path:
    return Path(cache_dir) / ANNOTATIONS_DIRNAME


def labels_path(cache_dir: Path) -> Path:
    return annotations_dir(cache_dir) / LABELS_FILENAME


def label_map_path(cache_dir: Path) -> Path:
    return annotations_dir(cache_dir) / LABEL_MAP_FILENAME


def edits_dir(cache_dir: Path) -> Path:
    return annotations_dir(cache_dir) / EDITS_DIRNAME


def edit_mask_path(cache_dir: Path, structure_name: str) -> Path:
    return edits_dir(cache_dir) / f"{structure_name}.nii.gz"


def annotations_exist(cache_dir: Path) -> bool:
    cache_dir = Path(cache_dir)
    if labels_path(cache_dir).is_file():
        return True
    edits = edits_dir(cache_dir)
    return edits.is_dir() and any(edits.glob("*.nii.gz"))


@dataclass
class LabelEntry:
    label_id: int
    name: str
    color_bgr: tuple[int, int, int]
    created: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "color_bgr": list(self.color_bgr),
            "created": self.created,
        }

    @classmethod
    def from_json(cls, label_id: int, raw: dict[str, Any]) -> LabelEntry:
        color = raw.get("color_bgr") or [0, 165, 255]
        return cls(
            label_id=label_id,
            name=str(raw.get("name") or f"label_{label_id}"),
            color_bgr=(int(color[0]), int(color[1]), int(color[2])),
            created=str(raw.get("created") or ""),
        )


@dataclass
class StrokeUndo:
    kind: PaintTargetKind
    structure_name: str | None
    slice_index: int
    y0: int
    y1: int
    x0: int
    x1: int
    before: np.ndarray


@dataclass
class AnnotateSession:
    """In-memory annotation state for one Series View session."""

    cache_dir: Path
    labels: np.ndarray  # uint16 Z,Y,X
    label_map: dict[int, LabelEntry] = field(default_factory=dict)
    ts_edits: dict[str, np.ndarray] = field(default_factory=dict)
    reference_image: sitk.Image | None = None
    undo_stack: list[StrokeUndo] = field(default_factory=list)
    dirty: bool = False

    @property
    def shape(self) -> tuple[int, int, int]:
        z, y, x = self.labels.shape
        return int(z), int(y), int(x)


def _empty_labels_from_geometry(geometry: dict) -> tuple[np.ndarray, sitk.Image]:
    ref = sitk_image_from_mask_geometry(geometry)
    size = ref.GetSize()
    labels = np.zeros((int(size[2]), int(size[1]), int(size[0])), dtype=np.uint16)
    return labels, ref


def _read_label_map(path: Path) -> dict[int, LabelEntry]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read label map %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, LabelEntry] = {}
    for key, value in raw.items():
        try:
            lid = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            out[lid] = LabelEntry.from_json(lid, value)
    return out


def _write_label_map(path: Path, label_map: dict[int, LabelEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {str(lid): entry.to_json() for lid, entry in sorted(label_map.items())}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_existing_edits(session: AnnotateSession) -> None:
    edits = edits_dir(session.cache_dir)
    if not edits.is_dir():
        return
    for path in sorted(edits.glob("*.nii.gz")):
        name = path.name[: -len(".nii.gz")]
        try:
            img = sitk.ReadImage(str(path))
            arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
            if arr.shape == session.labels.shape:
                session.ts_edits[name] = arr
        except RuntimeError as exc:
            logger.warning("Could not read edit mask %s: %s", path, exc)


def load_annotate_session(cache_dir: Path) -> AnnotateSession | None:
    """Load or create an annotation session when a volume grid is available."""
    cache_dir = Path(cache_dir)
    geometry = read_mask_geometry(cache_dir)
    volume_path = cache_dir / "volume.nii.gz"

    if geometry is not None:
        labels_file = labels_path(cache_dir)
        label_map = _read_label_map(label_map_path(cache_dir))
        if labels_file.is_file():
            try:
                img = sitk.ReadImage(str(labels_file))
                labels = sitk.GetArrayFromImage(img).astype(np.uint16, copy=False)
                ref = img
            except RuntimeError as exc:
                logger.warning("Could not read labels volume: %s", exc)
                labels, ref = _empty_labels_from_geometry(geometry)
        else:
            labels, ref = _empty_labels_from_geometry(geometry)
        session = AnnotateSession(
            cache_dir=cache_dir, labels=labels, label_map=label_map, reference_image=ref
        )
        _load_existing_edits(session)
        return session

    if not volume_path.is_file():
        return None
    try:
        ref = sitk.ReadImage(str(volume_path))
    except RuntimeError:
        return None
    size = ref.GetSize()
    labels = np.zeros((int(size[2]), int(size[1]), int(size[0])), dtype=np.uint16)
    label_map = _read_label_map(label_map_path(cache_dir))
    labels_file = labels_path(cache_dir)
    if labels_file.is_file():
        try:
            img = sitk.ReadImage(str(labels_file))
            arr = sitk.GetArrayFromImage(img).astype(np.uint16, copy=False)
            if arr.shape == labels.shape:
                labels = arr
                ref = img
        except RuntimeError as exc:
            logger.warning("Could not read labels volume: %s", exc)
    session = AnnotateSession(
        cache_dir=cache_dir, labels=labels, label_map=label_map, reference_image=ref
    )
    _load_existing_edits(session)
    return session


def next_label_id(label_map: dict[int, LabelEntry]) -> int:
    if not label_map:
        return 1
    return max(label_map) + 1


def next_label_color(label_map: dict[int, LabelEntry]) -> tuple[int, int, int]:
    used = {entry.color_bgr for entry in label_map.values()}
    for color in _USER_LABEL_PALETTE_BGR:
        if color not in used:
            return color
    return _USER_LABEL_PALETTE_BGR[len(label_map) % len(_USER_LABEL_PALETTE_BGR)]


def add_user_label(session: AnnotateSession, name: str) -> LabelEntry:
    name = name.strip() or f"label_{next_label_id(session.label_map)}"
    lid = next_label_id(session.label_map)
    entry = LabelEntry(
        label_id=lid,
        name=name,
        color_bgr=next_label_color(session.label_map),
        created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    session.label_map[lid] = entry
    session.dirty = True
    return entry


def ensure_ts_edit(
    session: AnnotateSession,
    structure_name: str,
    *,
    source_mask: np.ndarray,
) -> np.ndarray:
    """Return editable binary mask; seed from ``source_mask`` on first edit."""
    existing = session.ts_edits.get(structure_name)
    if existing is not None:
        return existing
    if source_mask.shape != session.labels.shape:
        raise ValueError(
            f"TS mask shape {source_mask.shape} != labels shape {session.labels.shape}"
        )
    edited = (source_mask > 0).astype(np.uint8).copy()
    session.ts_edits[structure_name] = edited
    session.dirty = True
    return edited


def save_annotate_session(session: AnnotateSession) -> None:
    """Write labels, label map, and TS edit masks to disk."""
    cache_dir = session.cache_dir
    ann = annotations_dir(cache_dir)
    ann.mkdir(parents=True, exist_ok=True)
    _write_label_map(label_map_path(cache_dir), session.label_map)

    ref = session.reference_image
    labels_img = sitk.GetImageFromArray(session.labels.astype(np.uint16, copy=False))
    if ref is not None:
        labels_img.CopyInformation(ref)
    sitk.WriteImage(labels_img, str(labels_path(cache_dir)), True)

    if session.ts_edits:
        edits = edits_dir(cache_dir)
        edits.mkdir(parents=True, exist_ok=True)
        for name, mask in session.ts_edits.items():
            img = sitk.GetImageFromArray(mask.astype(np.uint8, copy=False))
            if ref is not None:
                img.CopyInformation(ref)
            sitk.WriteImage(img, str(edit_mask_path(cache_dir, name)), True)

    session.dirty = False
    logger.info(
        "Saved annotations cache_dir=%s labels=%d edits=%d",
        cache_dir,
        len(session.label_map),
        len(session.ts_edits),
    )
