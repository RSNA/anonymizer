"""TS segmentation cache retention: JSON sidecars, mask pruning, and adaptive ROI."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

import SimpleITK as sitk
from pydicom import dcmread

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.config import (
    BRAIN_STRUCTURE_FILES,
    FACE_MASK_FILENAME,
    MIN_STRUCTURE_VOXELS,
    PRIMARY_SEGMENT_GROUPS,
    PRIMARY_SEGMENT_ORDER,
    PRIMARY_SEGMENT_PREFERRED_FILES,
    ROI_SUBSET_CHEST,
    ROI_SUBSET_FULL,
    ROI_SUBSET_HEAD,
    ROI_SUBSET_MANIFEST_FILENAME,
    ROI_TIER_CHEST,
    ROI_TIER_FULL,
    ROI_TIER_HEAD,
)
from anonymizer.controller.ai.tseg.dicom_geometry import sorted_dicom_paths
from anonymizer.controller.ai.tseg.modality_profile import resolve_profile_for_series
from anonymizer.utils.modalities import is_ct_modality

logger = logging.getLogger(__name__)

STRUCTURE_VOXELS_FILENAME = "structure_voxels.json"
PRIMARY_SEGMENT_VOXELS_FILENAME = "primary_segment_voxels.json"
MASK_GEOMETRY_FILENAME = "mask_geometry.json"

_LICENSED_MASK_STEMS = frozenset({"face", "face_mr", "vertebrae_body"})
_FACE_MASK_FILENAMES = frozenset({FACE_MASK_FILENAME, "face_mr.nii.gz"})


def _read_json_dict(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_dict(path: Path, payload: dict) -> None:
    """Write JSON via temp file + ``os.replace`` (atomic on the same filesystem)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    data = json.dumps(payload, indent=2) + "\n"
    try:
        tmp_path.write_text(data, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise


def resolve_primary_segment_files(seg_dir: Path, group_name: str) -> tuple[str, ...]:
    """Prefer a on-disk super-segment when configured; else the multi-file group list.

    MR ``total_mr`` writes combined ``vertebrae`` / whole-lung masks instead of CT
    per-vertebra and lobe files; detect those when the CT multi-file packs are absent.
    """
    fallback = PRIMARY_SEGMENT_GROUPS.get(group_name)
    if not fallback:
        raise KeyError(f"Unknown primary segment group: {group_name}")
    preferred = PRIMARY_SEGMENT_PREFERRED_FILES.get(group_name)
    if preferred and all((seg_dir / f"{stem}.nii.gz").is_file() for stem in preferred):
        return preferred

    if group_name == "spine" and (seg_dir / "vertebrae.nii.gz").is_file():
        has_ct_vertebrae = any(
            stem.startswith("vertebrae_") and (seg_dir / f"{stem}.nii.gz").is_file() for stem in fallback
        )
        if not has_ct_vertebrae:
            stems = ["vertebrae"]
            if (seg_dir / "sacrum.nii.gz").is_file():
                stems.append("sacrum")
            return tuple(stems)

    if group_name == "lungs":
        has_lobe = any((seg_dir / f"{stem}.nii.gz").is_file() for stem in fallback)
        if not has_lobe:
            mr_lungs = tuple(
                stem for stem in ("lung_left", "lung_right") if (seg_dir / f"{stem}.nii.gz").is_file()
            )
            if mr_lungs:
                return mr_lungs

    return fallback


def primary_segment_mask_stems_on_disk(seg_dir: Path, group_name: str) -> tuple[str, ...]:
    """Return resolved group stems that have ``.nii.gz`` masks under ``seg_dir``."""
    seg_dir = Path(seg_dir)
    return tuple(
        stem for stem in resolve_primary_segment_files(seg_dir, group_name) if (seg_dir / f"{stem}.nii.gz").is_file()
    )


def primary_segment_has_masks(seg_dir: Path, group_name: str) -> bool:
    """True when at least one Series View overlay mask for ``group_name`` exists on disk."""
    return bool(primary_segment_mask_stems_on_disk(seg_dir, group_name))


def overlay_masks_present(seg_dir: Path) -> bool:
    """True when ``seg/`` contains at least one ``.nii.gz`` anatomy mask for Series View overlays."""
    seg_dir = Path(seg_dir)
    return seg_dir.is_dir() and any(seg_dir.glob("*.nii.gz"))


def anatomy_overlay_cache_ready(cache_dir: Path) -> bool:
    """
    True when Harmonize left a usable Series View overlay cache.

    Requires ``structure_voxels.json``, ``primary_segment_voxels.json``, and on-disk
    ``seg/*.nii.gz`` masks for every listed primary group. JSON counts alone are not enough.
    """
    cache_dir = Path(cache_dir)
    if read_structure_voxels(cache_dir) is None:
        return False
    primary = read_primary_segment_voxels(cache_dir)
    if primary is None:
        return False
    seg_dir = cache_dir / "seg"
    if not primary:
        # No anatomy groups above threshold — still ready when voxel sidecar exists.
        return True
    if not overlay_masks_present(seg_dir):
        return False
    return all(primary_segment_has_masks(seg_dir, name) for name in primary)


def reconcile_primary_segment_sidecar(cache_dir: Path) -> dict[str, int]:
    """
    Rewrite ``primary_segment_voxels.json`` from structure counts ∩ on-disk masks.

    Repairs stats-only caches that listed overlay groups without writing ``seg/*.nii.gz``.
    """
    cache_dir = Path(cache_dir)
    structure = read_structure_voxels(cache_dir) or {}
    primary = aggregate_primary_segment_voxels(
        structure,
        cache_dir / "seg",
        require_masks=True,
    )
    write_primary_segment_voxels(cache_dir, primary)
    return primary


def read_structure_voxels(cache_dir: Path) -> dict[str, int] | None:
    payload = _read_json_dict(Path(cache_dir) / STRUCTURE_VOXELS_FILENAME)
    if payload is None:
        return None
    counts: dict[str, int] = {}
    for key, value in payload.items():
        try:
            counts[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return counts or None


def write_structure_voxels(cache_dir: Path, counts: dict[str, int]) -> Path:
    path = Path(cache_dir) / STRUCTURE_VOXELS_FILENAME
    _write_json_dict(path, {key: int(value) for key, value in sorted(counts.items())})
    return path


def read_primary_segment_voxels(cache_dir: Path) -> dict[str, int] | None:
    payload = _read_json_dict(Path(cache_dir) / PRIMARY_SEGMENT_VOXELS_FILENAME)
    if payload is None:
        return None
    counts: dict[str, int] = {}
    for key, value in payload.items():
        try:
            counts[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return counts or None


def write_primary_segment_voxels(cache_dir: Path, counts: dict[str, int]) -> Path:
    path = Path(cache_dir) / PRIMARY_SEGMENT_VOXELS_FILENAME
    _write_json_dict(path, {key: int(value) for key, value in sorted(counts.items())})
    return path


def mask_geometry_from_image(image: sitk.Image) -> dict:
    size = image.GetSize()
    spacing = image.GetSpacing()
    origin = image.GetOrigin()
    direction = image.GetDirection()
    return {
        "size": [int(size[i]) for i in range(len(size))],
        "spacing": [float(spacing[i]) for i in range(len(spacing))],
        "origin": [float(origin[i]) for i in range(len(origin))],
        "direction": [float(direction[i]) for i in range(len(direction))],
    }


def read_mask_geometry(cache_dir: Path) -> dict | None:
    payload = _read_json_dict(Path(cache_dir) / MASK_GEOMETRY_FILENAME)
    if payload is None:
        return None
    required = ("size", "spacing", "origin", "direction")
    if not all(key in payload for key in required):
        return None
    return payload


def write_mask_geometry(cache_dir: Path, seg_dir: Path) -> Path | None:
    seg_dir = Path(seg_dir)
    reference: sitk.Image | None = None
    for mask_path in sorted(seg_dir.glob("*.nii.gz")):
        if mask_path.name in _FACE_MASK_FILENAMES:
            continue
        try:
            reference = sitk.ReadImage(str(mask_path))
            break
        except RuntimeError:
            continue
    if reference is None:
        return None
    try:
        payload = mask_geometry_from_image(reference)
    finally:
        del reference
    path = Path(cache_dir) / MASK_GEOMETRY_FILENAME
    _write_json_dict(path, payload)
    return path


def sitk_image_from_mask_geometry(payload: dict) -> sitk.Image:
    image = sitk.Image(
        [int(value) for value in payload["size"]],
        sitk.sitkUInt8,
    )
    image.SetSpacing([float(value) for value in payload["spacing"]])
    image.SetOrigin([float(value) for value in payload["origin"]])
    image.SetDirection([float(value) for value in payload["direction"]])
    return image


def aggregate_primary_segment_voxels(
    structure_voxels: dict[str, int],
    seg_dir: Path,
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
    require_masks: bool = True,
) -> dict[str, int]:
    """Sum per-structure counts into primary Series View overlay groups.

    By default only groups with at least one on-disk ``.nii.gz`` are included so
    ``primary_segment_voxels.json`` never advertises overlays that cannot be drawn.
    Pass ``require_masks=False`` only when aggregating from statistics before masks exist.
    """
    seg_dir = Path(seg_dir)
    present: dict[str, int] = {}
    for group_name in PRIMARY_SEGMENT_ORDER:
        files = resolve_primary_segment_files(seg_dir, group_name)
        if require_masks:
            files = primary_segment_mask_stems_on_disk(seg_dir, group_name)
            if not files:
                continue
        total = sum(int(structure_voxels.get(stem, 0)) for stem in files)
        if total >= min_voxels:
            present[group_name] = total
    return present


def latch_mask_stems_for_export(
    structure_voxels: dict[str, int],
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
) -> set[str]:
    """Stems to persist for Series View overlays from structure counts (no disk required)."""
    keep: set[str] = set()
    for group_name in PRIMARY_SEGMENT_ORDER:
        files = PRIMARY_SEGMENT_GROUPS[group_name]
        preferred = PRIMARY_SEGMENT_PREFERRED_FILES.get(group_name)
        if preferred:
            preferred_stems = [stem for stem in preferred if int(structure_voxels.get(stem, 0)) > 0]
            if preferred_stems:
                total = sum(int(structure_voxels.get(stem, 0)) for stem in preferred_stems)
                if total >= min_voxels:
                    keep.update(preferred_stems)
                continue
        stems = [stem for stem in files if int(structure_voxels.get(stem, 0)) > 0]
        total = sum(int(structure_voxels.get(stem, 0)) for stem in stems)
        if total >= min_voxels:
            keep.update(stems)
    return keep


def clear_anatomy_seg_masks(seg_dir: Path) -> None:
    """Remove anatomy ``*.nii.gz`` under ``seg/`` (keeps face masks)."""
    seg_dir = Path(seg_dir)
    if not seg_dir.is_dir():
        return
    for mask_path in seg_dir.glob("*.nii.gz"):
        if mask_path.name in _FACE_MASK_FILENAMES:
            continue
        try:
            mask_path.unlink()
        except OSError as exc:
            logger.warning("TS cache: could not remove %s: %s", mask_path, exc)


def write_binary_masks_from_multilabel(
    multilabel_img,
    seg_dir: Path,
    stems: set[str],
    *,
    task: str = "total",
) -> list[str]:
    """
    Write selected binary ``*.nii.gz`` masks from an in-memory multilabel NIfTI.

    ``multilabel_img`` is a nibabel ``Nifti1Image`` (TotalSegmentator ``ml=True`` return).
    """
    import nibabel as nib
    import numpy as np
    from totalsegmentator.map_to_binary import class_map

    if task not in class_map:
        raise KeyError(f"Unknown TotalSegmentator class map task: {task!r}")
    name_to_label = {name: int(label) for label, name in class_map[task].items()}
    seg_dir = Path(seg_dir)
    seg_dir.mkdir(parents=True, exist_ok=True)
    data = np.asanyarray(multilabel_img.dataobj)
    affine = multilabel_img.affine
    written: list[str] = []
    for stem in sorted(stems):
        label = name_to_label.get(stem)
        if label is None:
            logger.debug("TS cache: skip export for unknown label stem %r", stem)
            continue
        binary = (data == label).astype(np.uint8)
        if not binary.any():
            continue
        out_img = nib.Nifti1Image(binary, affine)
        out_path = seg_dir / f"{stem}.nii.gz"
        nib.save(out_img, str(out_path))
        written.append(stem)
    return written


def compute_latch_mask_keep_set(
    seg_dir: Path,
    structure_voxels: dict[str, int],
    primary_segment_voxels: dict[str, int],
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
) -> set[str]:
    """Mask file stems required for Series View overlay buttons and licensed tasks."""
    seg_dir = Path(seg_dir)
    keep: set[str] = set()

    for group_name, group_count in primary_segment_voxels.items():
        if group_count < min_voxels:
            continue
        files = resolve_primary_segment_files(seg_dir, group_name)
        preferred = PRIMARY_SEGMENT_PREFERRED_FILES.get(group_name)
        if preferred:
            preferred_present = [
                stem
                for stem in preferred
                if structure_voxels.get(stem, 0) > 0 and (seg_dir / f"{stem}.nii.gz").is_file()
            ]
            if preferred_present:
                keep.update(preferred_present)
                continue
        for stem in files:
            if structure_voxels.get(stem, 0) > 0 and (seg_dir / f"{stem}.nii.gz").is_file():
                keep.add(stem)

    for stem in _LICENSED_MASK_STEMS:
        if (seg_dir / f"{stem}.nii.gz").is_file():
            keep.add(stem)

    for name in BRAIN_STRUCTURE_FILES:
        if structure_voxels.get(name, 0) >= min_voxels and (seg_dir / f"{name}.nii.gz").is_file():
            keep.add(name)

    return keep


def prune_seg_cache(
    seg_dir: Path,
    *,
    structure_voxels: dict[str, int],
    primary_segment_voxels: dict[str, int],
) -> list[str]:
    """Delete seg masks not needed for Series View overlays; return removed stems."""
    seg_dir = Path(seg_dir)
    if not seg_dir.is_dir():
        return []

    keep = compute_latch_mask_keep_set(seg_dir, structure_voxels, primary_segment_voxels)
    removed: list[str] = []
    for mask_path in seg_dir.glob("*.nii.gz"):
        stem = mask_path.name[: -len(".nii.gz")]
        if stem in keep:
            continue
        try:
            mask_path.unlink()
            removed.append(stem)
        except OSError as exc:
            logger.warning("TS cache: could not remove %s: %s", mask_path, exc)
    if removed:
        logger.debug("TS cache: pruned %d mask(s) under %s", len(removed), seg_dir)
    return removed


def structure_voxels_sidecar_valid(cache_dir: Path, structures: list[str]) -> bool:
    counts = read_structure_voxels(cache_dir)
    if counts is None:
        return False
    requested = set(structures)
    if not requested <= set(counts.keys()):
        return False
    return any(counts.get(name, 0) > 0 for name in requested)


def finalize_seg_cache(
    cache_dir: Path,
    seg_dir: Path,
    structure_voxels: dict[str, int],
) -> dict[str, int]:
    """
    Publish Harmonize segment results as one logical unit.

    Call only after TotalSegmentator has written ``seg/*.nii.gz``. Order:

    1. Prune ``seg/`` to overlay-essential masks (files settle first).
    2. Write ``mask_geometry.json`` from a remaining mask.
    3. Write ``structure_voxels.json``.
    4. Write ``primary_segment_voxels.json`` last — derived only from masks still
       on disk (``require_masks=True``). Readers treat this file as the overlay
       catalog; it must never list groups without files.

    JSON files use temp+replace. This is not a multi-file filesystem transaction,
    but consumers never see a non-empty primary catalog without matching masks,
    and a crash before step 4 leaves the previous primary (or none) rather than
    a stats-only ghost catalog.
    """
    cache_dir = Path(cache_dir)
    seg_dir = Path(seg_dir)
    primary_counts = aggregate_primary_segment_voxels(
        structure_voxels,
        seg_dir,
        require_masks=True,
    )
    prune_seg_cache(seg_dir, structure_voxels=structure_voxels, primary_segment_voxels=primary_counts)
    # Re-aggregate after prune in case preferred stems changed keep-set.
    primary_counts = aggregate_primary_segment_voxels(
        structure_voxels,
        seg_dir,
        require_masks=True,
    )
    write_mask_geometry(cache_dir, seg_dir)
    write_structure_voxels(cache_dir, structure_voxels)
    write_primary_segment_voxels(cache_dir, primary_counts)
    if any(int(v) > 0 for v in structure_voxels.values()) and not overlay_masks_present(seg_dir):
        raise RuntimeError(
            f"Refusing to publish segment cache under {cache_dir}: "
            "structure counts are non-zero but seg/ has no overlay masks. "
            "Write masks before finalize_seg_cache."
        )
    return primary_counts


def resolve_harmonize_roi_subset(series_directory: Path) -> tuple[tuple[str, ...], str]:
    """Choose CT ROI tier from DICOM metadata (HEAD / CHEST / FULL)."""
    from anonymizer.controller.ai.blur_face.pipeline import MetadataSignal, metadata_signal

    series_directory = Path(series_directory)
    try:
        paths = sorted_dicom_paths(series_directory)
    except ValueError:
        return ROI_SUBSET_FULL, ROI_TIER_FULL
    if not paths:
        return ROI_SUBSET_FULL, ROI_TIER_FULL

    ds = dcmread(paths[0], stop_before_pixels=True)
    signal = metadata_signal(ds)
    body_part = str(getattr(ds, "BodyPartExamined", "") or "").strip().upper()
    study_text = str(getattr(ds, "StudyDescription", "") or "").strip().upper()
    combined = f"{body_part} {study_text}"

    if any(token in combined for token in ("ABDOM", "PELV", "CAP", "WHOLE BODY", "WBD")):
        return ROI_SUBSET_FULL, ROI_TIER_FULL
    if signal == MetadataSignal.HEAD or any(token in combined for token in ("HEAD", "BRAIN", "SKULL")):
        return ROI_SUBSET_HEAD, ROI_TIER_HEAD
    if signal == MetadataSignal.NON_HEAD or any(
        token in combined for token in ("CHEST", "THOR", "THORAX", "LUNG", "BREAST")
    ):
        return ROI_SUBSET_CHEST, ROI_TIER_CHEST
    return ROI_SUBSET_FULL, ROI_TIER_FULL


def read_roi_tier(cache_dir: Path) -> str | None:
    path = Path(cache_dir) / ROI_SUBSET_MANIFEST_FILENAME
    payload = _read_json_dict(path)
    if payload is None:
        return None
    tier = payload.get("roi_tier")
    return str(tier) if tier is not None else None


def widen_roi_tier(tier: str) -> tuple[tuple[str, ...], str] | None:
    if tier == ROI_TIER_HEAD:
        return ROI_SUBSET_CHEST, ROI_TIER_CHEST
    if tier == ROI_TIER_CHEST:
        return ROI_SUBSET_FULL, ROI_TIER_FULL
    return None


def _series_instance_uid(series_directory: Path) -> str | None:
    try:
        paths = sorted_dicom_paths(series_directory)
    except ValueError:
        return None
    if not paths:
        return None
    ds = dcmread(paths[0], stop_before_pixels=True)
    uid = getattr(ds, "SeriesInstanceUID", None)
    return str(uid) if uid else None


def is_ct_head_series(series_directory: Path) -> bool:
    """True for CT series classified as head-dominant (face-blur candidate)."""
    # Lazy: blur_face.pipeline imports segment, which imports this module.
    from anonymizer.controller.ai.blur_face.pipeline import (
        CachedRegionSignal,
        MetadataSignal,
        cached_region_signal,
        metadata_signal,
    )

    profile = resolve_profile_for_series(series_directory)
    if profile is None or not is_ct_modality(profile.modality):
        return False

    region_signal = cached_region_signal(series_directory)
    if region_signal == CachedRegionSignal.HEAD:
        return True
    if region_signal in (CachedRegionSignal.NON_HEAD, CachedRegionSignal.MULTI_REGION):
        return False

    try:
        paths = sorted_dicom_paths(series_directory)
        ds = dcmread(paths[0], stop_before_pixels=True)
    except (ValueError, OSError):
        return False
    return metadata_signal(ds) == MetadataSignal.HEAD


def retain_volume_for_pending_face_blur(series_directory: Path, anon_model=None) -> bool:
    """Keep NIfTI until manual face blur has been applied on a CT head study."""
    if not is_ct_head_series(series_directory):
        return False
    if anon_model is None:
        return True
    series_uid = _series_instance_uid(series_directory)
    if series_uid is None:
        return True
    return not anon_model.series_has_face_blur(series_uid)


def evict_tseg_volume(series_directory: Path, anon_model=None) -> bool:
    """Remove cached ``volume.nii.gz`` after TS work for a series is complete.

    Segmentation sidecars (``structure_voxels.json``) must exist so harmonize and
    overlays do not depend on the NIfTI. Call only when the caller has finished
    all TS stages for this series (segmentation, contrast, brain structures, …).

    CT head studies keep the volume until face blur has been manually applied
    (``face_blur_algorithm_applied`` in the project DB), so the face task can reuse
    the cached NIfTI without a DICOM reconversion.
    """
    cache_dir = resolve_series_cache_dir(series_directory)
    volume_path = cache_dir / "volume.nii.gz"
    if not volume_path.is_file():
        return False
    if read_structure_voxels(cache_dir) is None:
        logger.debug("TS cache: keeping volume (segmentation sidecars missing) for %s", series_directory)
        return False
    if retain_volume_for_pending_face_blur(series_directory, anon_model):
        logger.debug("TS cache: keeping volume for pending face blur on %s", series_directory)
        return False

    try:
        volume_path.unlink()
        logger.info("TS cache: evicted volume NIfTI for %s", series_directory)
        return True
    except OSError as exc:
        logger.warning("TS cache: could not evict volume for %s: %s", series_directory, exc)
        return False
