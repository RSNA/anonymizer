"""Import researcher NIfTI/NRRD segmentations into the annotation store."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.seg_retention import (
    MASK_GEOMETRY_FILENAME,
    mask_geometry_from_image,
)
from anonymizer.controller.annotations.store import (
    LABEL_MAP_FILENAME,
    AnnotateSession,
    LabelEntry,
    add_user_label,
    load_annotate_session,
    next_label_color,
    next_label_id,
    save_annotate_session,
)

logger = logging.getLogger(__name__)

VOLUME_EXTENSIONS = (".nii", ".nii.gz", ".nrrd", ".seg.nrrd")
_LABEL_FILE_SUFFIXES = (".label", ".txt")


class ImportProfile(str, Enum):
    AUTO = "auto"
    MULTILABEL = "multilabel"
    BINARY_MASKS = "binary_masks"
    FOLDER_TS = "folder_ts"
    ITK_SNAP = "itk_snap"
    NNUNET = "nnunet"


@dataclass(frozen=True)
class ImportResult:
    entries: list[LabelEntry]
    profile: ImportProfile
    resampled: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ResolvedLabel:
    """External voxel id → display name + optional BGR color."""

    name: str
    color_bgr: tuple[int, int, int] | None = None


def _stem_without_nii(path: Path) -> str:
    name = path.name
    lower = name.lower()
    if lower.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    if lower.endswith(".seg.nrrd"):
        return name[: -len(".seg.nrrd")]
    return path.stem


def is_volume_path(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(ext) for ext in VOLUME_EXTENSIONS)


def list_volume_paths(directory: Path) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and is_volume_path(path):
            found.append(path)
    return found


def parse_anonymizer_label_map(path: Path) -> dict[int, _ResolvedLabel]:
    """Parse our ``label_map.json`` (id → {name, color_bgr})."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse label_map %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, _ResolvedLabel] = {}
    for key, value in raw.items():
        try:
            lid = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or f"label_{lid}")
        color = value.get("color_bgr")
        color_bgr = None
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            color_bgr = (int(color[0]), int(color[1]), int(color[2]))
        out[lid] = _ResolvedLabel(name=name, color_bgr=color_bgr)
    return out


def parse_itk_snap_label_file(path: Path) -> dict[int, _ResolvedLabel]:
    """Parse ITK-SNAP Label Descriptions (``.label`` / ``.txt``).

    Format: ``IDX R G B A VIS MSH "LABEL"``
    """
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.warning("Could not read ITK-SNAP label file %s: %s", path, exc)
        return {}
    # Alpha may be 0/1 or 0.00–1.00
    color_line = re.compile(
        r'^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([0-9.]+)\s+([01])\s+([01])\s+"([^"]*)"'
    )
    out: dict[int, _ResolvedLabel] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = color_line.match(line)
        if not match:
            continue
        idx = int(match.group(1))
        if idx == 0:
            continue
        r, g, b = int(match.group(2)), int(match.group(3)), int(match.group(4))
        name = match.group(8).strip() or f"label_{idx}"
        out[idx] = _ResolvedLabel(name=name, color_bgr=(b, g, r))
    return out


def parse_nnunet_dataset_json(path: Path) -> dict[int, _ResolvedLabel]:
    """Parse nnU-Net ``dataset.json`` labels (v2 name→int) or MSD-style (int→name)."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse nnU-Net dataset.json %s: %s", path, exc)
        return {}
    labels = raw.get("labels") if isinstance(raw, dict) else None
    if not isinstance(labels, dict):
        return {}
    out: dict[int, _ResolvedLabel] = {}
    for key, value in labels.items():
        # nnU-Net v2: name → int (or region tuple — skip tuples)
        if isinstance(value, (list, tuple)):
            continue
        if isinstance(value, int) or (isinstance(value, str) and str(value).isdigit()):
            try:
                lid = int(value)
            except (TypeError, ValueError):
                continue
            name = str(key)
            if lid == 0 or name.lower() == "background":
                continue
            out[lid] = _ResolvedLabel(name=name)
            continue
        # Medical Decathlon / older: "1" → "Anterior"
        try:
            lid = int(key)
        except (TypeError, ValueError):
            continue
        if lid == 0:
            continue
        if isinstance(value, str):
            out[lid] = _ResolvedLabel(name=value)
    return out


def parse_int_to_name_json(path: Path) -> dict[int, _ResolvedLabel]:
    """TotalSegmentator-style / generic ``{ "1": "liver", ... }`` or nested maps."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # map_to_binary is often name → filename; look for int keys
    out: dict[int, _ResolvedLabel] = {}
    for key, value in raw.items():
        try:
            lid = int(key)
        except (TypeError, ValueError):
            continue
        if lid == 0:
            continue
        if isinstance(value, str):
            out[lid] = _ResolvedLabel(name=value)
        elif isinstance(value, dict) and "name" in value:
            out[lid] = _ResolvedLabel(name=str(value["name"]))
    return out


def _find_sidecar(volume_path: Path, names: tuple[str, ...]) -> Path | None:
    parent = volume_path.parent
    for name in names:
        candidate = parent / name
        if candidate.is_file():
            return candidate
    return None


def _find_itk_snap_label_sidecar(volume_path: Path) -> Path | None:
    parent = volume_path.parent
    stem = _stem_without_nii(volume_path)
    for suffix in _LABEL_FILE_SUFFIXES:
        for candidate in (parent / f"{stem}{suffix}", parent / f"labels{suffix}"):
            if candidate.is_file():
                return candidate
    # Any single .label in the folder
    labels = sorted(parent.glob("*.label"))
    if len(labels) == 1:
        return labels[0]
    return None


def _find_nnunet_dataset_json(volume_path: Path) -> Path | None:
    parent = volume_path.parent
    for candidate in (parent / "dataset.json", parent.parent / "dataset.json"):
        if candidate.is_file():
            return candidate
    return None


def resolve_label_names(
    volume_path: Path,
    *,
    profile: ImportProfile,
    present_ids: set[int],
) -> tuple[dict[int, _ResolvedLabel], ImportProfile, tuple[str, ...]]:
    """Pick the best sidecar for multi-label name resolution."""
    warnings: list[str] = []
    resolved: dict[int, _ResolvedLabel] = {}
    used = profile

    if profile in (ImportProfile.AUTO, ImportProfile.MULTILABEL, ImportProfile.ITK_SNAP, ImportProfile.NNUNET):
        ours = _find_sidecar(volume_path, (LABEL_MAP_FILENAME,))
        if ours is not None and profile in (ImportProfile.AUTO, ImportProfile.MULTILABEL):
            resolved = parse_anonymizer_label_map(ours)
            if resolved:
                used = ImportProfile.MULTILABEL

        if not resolved and profile in (ImportProfile.AUTO, ImportProfile.ITK_SNAP):
            itk = _find_itk_snap_label_sidecar(volume_path)
            if itk is not None:
                resolved = parse_itk_snap_label_file(itk)
                if resolved:
                    used = ImportProfile.ITK_SNAP

        if not resolved and profile in (ImportProfile.AUTO, ImportProfile.NNUNET):
            nn = _find_nnunet_dataset_json(volume_path)
            if nn is not None:
                resolved = parse_nnunet_dataset_json(nn)
                if resolved:
                    used = ImportProfile.NNUNET

        if not resolved and profile == ImportProfile.AUTO:
            for name in ("map_to_binary.json", "class_map.json", "labels.json"):
                side = volume_path.parent / name
                if side.is_file():
                    resolved = parse_int_to_name_json(side)
                    if resolved:
                        break

    for lid in sorted(present_ids):
        if lid not in resolved:
            resolved[lid] = _ResolvedLabel(name=f"label_{lid}")
            if profile != ImportProfile.AUTO:
                warnings.append(f"No sidecar name for label id {lid}; using label_{lid}")

    if used == ImportProfile.AUTO:
        used = ImportProfile.MULTILABEL
    return resolved, used, tuple(warnings)


def ensure_series_annotation_geometry(
    series_dir: Path,
    cache_dir: Path,
) -> AnnotateSession:
    """Load or create an annotate session with volume + mask geometry for ``series_dir``."""
    cache_dir = Path(cache_dir)
    session = load_annotate_session(cache_dir)
    if session is not None:
        return session

    from anonymizer.controller.ai.tseg.dicom_geometry import build_sitk_volume_from_series_frames
    from anonymizer.controller.series_io import load_series_frames

    series_dir = Path(series_dir)
    loaded = load_series_frames(series_dir)
    volume = build_sitk_volume_from_series_frames(loaded.metadata, loaded.frames, loaded.slice_paths)
    cache_dir.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(volume, str(cache_dir / "volume.nii.gz"), True)
    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(volume)) + "\n", encoding="utf-8"
    )
    session = load_annotate_session(cache_dir)
    if session is None:
        raise RuntimeError(f"Failed to create annotation geometry under {cache_dir}")
    return session


def _geometry_matches(a: sitk.Image, b: sitk.Image, *, atol: float = 1e-4) -> bool:
    if a.GetSize() != b.GetSize():
        return False
    if not np.allclose(a.GetSpacing(), b.GetSpacing(), atol=atol, rtol=0):
        return False
    if not np.allclose(a.GetOrigin(), b.GetOrigin(), atol=atol, rtol=0):
        return False
    return bool(np.allclose(a.GetDirection(), b.GetDirection(), atol=atol, rtol=0))


def align_label_image_to_reference(
    source: sitk.Image,
    reference: sitk.Image,
) -> tuple[sitk.Image, bool, str | None]:
    """Return label image on ``reference`` grid; nearest-neighbor when resampling."""
    if _geometry_matches(source, reference):
        return source, False, None
    if source.GetSize() == reference.GetSize():
        # Same array shape, meta differs — keep voxels, adopt reference geometry for storage.
        out = sitk.GetImageFromArray(sitk.GetArrayFromImage(source))
        out.CopyInformation(reference)
        return out, False, "Label geometry metadata differed; voxels kept on series grid"
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    resampler.SetDefaultPixelValue(0)
    resampler.SetOutputPixelType(source.GetPixelID())
    out = resampler.Execute(source)
    return out, True, "Label volume resampled (nearest-neighbor) onto series grid"


def _read_label_volume(path: Path) -> sitk.Image:
    try:
        return sitk.ReadImage(str(path))
    except RuntimeError as exc:
        raise ValueError(f"Could not read segment volume: {path.name}") from exc


def _array_zyx(img: sitk.Image) -> np.ndarray:
    return sitk.GetArrayFromImage(img)


def _add_label_entry(
    session: AnnotateSession,
    name: str,
    *,
    color_bgr: tuple[int, int, int] | None = None,
) -> LabelEntry:
    if color_bgr is not None:
        lid = next_label_id(session.label_map)
        entry = LabelEntry(
            label_id=lid,
            name=name.strip() or f"label_{lid}",
            color_bgr=color_bgr,
            created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        session.label_map[lid] = entry
        session.dirty = True
        return entry
    return add_user_label(session, name)


def import_binary_masks(
    session: AnnotateSession,
    paths: list[Path],
    *,
    names: list[str] | None = None,
) -> ImportResult:
    """Import one or more binary masks; non-zero voxels become a new user label each."""
    if session.reference_image is None:
        raise ValueError("Annotation session has no reference geometry")
    ref = session.reference_image
    warnings: list[str] = []
    entries: list[LabelEntry] = []
    any_resampled = False
    for i, path in enumerate(paths):
        path = Path(path)
        name = (names[i] if names and i < len(names) else None) or _stem_without_nii(path)
        source = _read_label_volume(path)
        aligned, resampled, warn = align_label_image_to_reference(source, ref)
        if warn:
            warnings.append(warn)
        any_resampled = any_resampled or resampled
        arr = _array_zyx(aligned)
        if arr.shape != session.labels.shape:
            raise ValueError(
                f"Mask shape {arr.shape} does not match series labels {session.labels.shape} ({path.name})"
            )
        if not np.any(arr):
            warnings.append(f"Empty mask skipped: {path.name}")
            continue
        # Avoid palette collision when many masks share default colors
        color = next_label_color(session.label_map)
        entry = _add_label_entry(session, name, color_bgr=color)
        session.labels[arr > 0] = entry.label_id
        entries.append(entry)
    if entries:
        save_annotate_session(session)
    return ImportResult(
        entries=entries,
        profile=ImportProfile.BINARY_MASKS,
        resampled=any_resampled,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def import_label_nifti(
    session: AnnotateSession,
    path: Path,
    *,
    profile: ImportProfile = ImportProfile.AUTO,
    label_names: dict[int, _ResolvedLabel] | None = None,
) -> ImportResult:
    """Import a multi-class integer label volume into the annotate session."""
    if session.reference_image is None:
        raise ValueError("Annotation session has no reference geometry")
    path = Path(path)
    source = _read_label_volume(path)
    aligned, resampled, warn = align_label_image_to_reference(source, session.reference_image)
    warnings: list[str] = []
    if warn:
        warnings.append(warn)
    arr = np.rint(_array_zyx(aligned)).astype(np.int32, copy=False)
    if arr.shape != session.labels.shape:
        raise ValueError(f"Label shape {arr.shape} does not match series {session.labels.shape}")

    present_ids = {int(v) for v in np.unique(arr) if int(v) > 0}
    if not present_ids:
        raise ValueError(f"No positive labels found in {path.name}")

    if label_names is None:
        resolved, used_profile, side_warn = resolve_label_names(path, profile=profile, present_ids=present_ids)
        warnings.extend(side_warn)
    else:
        resolved = dict(label_names)
        for lid in present_ids:
            if lid not in resolved:
                resolved[lid] = _ResolvedLabel(name=f"label_{lid}")
        used_profile = profile if profile != ImportProfile.AUTO else ImportProfile.MULTILABEL

    entries: list[LabelEntry] = []
    for ext_id in sorted(present_ids):
        meta = resolved.get(ext_id) or _ResolvedLabel(name=f"label_{ext_id}")
        color = meta.color_bgr if meta.color_bgr is not None else next_label_color(session.label_map)
        entry = _add_label_entry(session, meta.name, color_bgr=color)
        session.labels[arr == ext_id] = entry.label_id
        entries.append(entry)

    save_annotate_session(session)
    return ImportResult(
        entries=entries,
        profile=used_profile,
        resampled=resampled,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def import_folder_binary_masks(session: AnnotateSession, directory: Path) -> ImportResult:
    """TotalSegmentator-style folder: each ``*.nii.gz`` (etc.) is one binary structure."""
    paths = list_volume_paths(directory)
    if not paths:
        raise ValueError(f"No NIfTI/NRRD masks found in {directory}")
    result = import_binary_masks(session, paths)
    return ImportResult(
        entries=result.entries,
        profile=ImportProfile.FOLDER_TS,
        resampled=result.resampled,
        warnings=result.warnings,
    )


def detect_and_import(
    session: AnnotateSession,
    *,
    paths: list[Path] | None = None,
    folder: Path | None = None,
    profile: ImportProfile = ImportProfile.AUTO,
) -> ImportResult:
    """High-level import used by Series View (files and/or folder)."""
    if folder is not None:
        return import_folder_binary_masks(session, folder)

    if not paths:
        raise ValueError("No segment files selected")

    paths = [Path(p) for p in paths]
    if profile == ImportProfile.FOLDER_TS:
        if len(paths) == 1 and paths[0].is_dir():
            return import_folder_binary_masks(session, paths[0])
        return import_binary_masks(session, paths)

    if profile == ImportProfile.BINARY_MASKS or (profile == ImportProfile.AUTO and len(paths) > 1):
        return import_binary_masks(session, paths)

    # Single volume — multi-label (Slicer / ITK-SNAP / nnU-Net / MITK / our bundle)
    if len(paths) != 1:
        return import_binary_masks(session, paths)

    vol = paths[0]
    if profile in (ImportProfile.ITK_SNAP, ImportProfile.NNUNET, ImportProfile.MULTILABEL, ImportProfile.AUTO):
        return import_label_nifti(session, vol, profile=profile)
    return import_label_nifti(session, vol, profile=ImportProfile.AUTO)
