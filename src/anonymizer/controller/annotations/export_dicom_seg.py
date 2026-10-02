"""DICOM Segmentation IOD export from multi-class label volumes."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    ExplicitVRLittleEndian,
    SegmentationStorage,
    generate_uid,
)

from anonymizer.controller.annotations.store import (
    AnnotateSession,
    LabelEntry,
    edits_dir,
    labels_path,
    load_annotate_session,
    next_label_color,
    next_label_id,
    normalize_label_name,
    read_label_map,
    resolve_normative_organ,
    save_annotate_session,
)

logger = logging.getLogger(__name__)

# Face Blur masks are not clinical anatomy segments for DICOM-SEG export.
_FACE_MASK_STEMS = frozenset({"face", "face_mr"})


def count_exportable_segment_labels(cache_dir: Path) -> int:
    """Count unique exportable segment labels under a series ``0_TS_SEG`` cache.

    Matches DICOM-SEG inventory rules without loading NIfTI volumes: user
    ``label_map.json`` names, plus ``seg/*.nii.gz`` and ``annotations/edits/*.nii.gz``
    stems not already present (Face Blur stems excluded). Dedupes by normalized name.
    """
    cache_dir = Path(cache_dir)
    names: set[str] = set()
    for entry in read_label_map(cache_dir).values():
        key = normalize_label_name(entry.name)
        if key:
            names.add(key)

    seg_dir = cache_dir / "seg"
    if seg_dir.is_dir():
        for path in seg_dir.glob("*.nii.gz"):
            stem = path.name[: -len(".nii.gz")]
            if stem in _FACE_MASK_STEMS:
                continue
            key = normalize_label_name(stem)
            if key:
                names.add(key)

    edits = edits_dir(cache_dir)
    if edits.is_dir():
        for path in edits.glob("*.nii.gz"):
            stem = path.name[: -len(".nii.gz")]
            if stem in _FACE_MASK_STEMS:
                continue
            key = normalize_label_name(stem)
            if key:
                names.add(key)

    return len(names)


def count_patient_exportable_segment_labels(patient_dir: Path) -> int:
    """Sum exportable segment labels across all series under a patient directory."""
    from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir

    patient_dir = Path(patient_dir)
    if not patient_dir.is_dir():
        return 0
    total = 0
    for study_path in patient_dir.iterdir():
        if not study_path.is_dir() or study_path.name.startswith("."):
            continue
        for series_path in study_path.iterdir():
            if not series_path.is_dir() or series_path.name.startswith("."):
                continue
            total += count_exportable_segment_labels(resolve_series_cache_dir(series_path))
    return total


def _paint_binary_label(
    session: AnnotateSession,
    name: str,
    mask: np.ndarray,
    *,
    occupied_names: set[str],
    binary_masks: dict[int, np.ndarray],
) -> str | None:
    """Add ``mask`` as a new segment label; skip empty / duplicate names.

    TotalSegmentator masks are stored independently in ``binary_masks`` so
    overlapping structures (e.g. brain ⊃ frontal_lobe) keep full coverage in
    DICOM-SEG frames. Returns the label name when painted, else None.
    """
    key = normalize_label_name(name)
    if not key or key in occupied_names:
        return None
    if mask.shape != session.labels.shape:
        logger.warning(
            "Skip DICOM-SEG mask %s: shape %s != labels %s",
            name,
            mask.shape,
            session.labels.shape,
        )
        return None
    binary = (mask > 0).astype(np.uint8)
    if not np.any(binary):
        return None
    lid = next_label_id(session.label_map)
    entry = LabelEntry(
        label_id=lid,
        name=name,
        color_bgr=next_label_color(session.label_map),
        normative_organ=resolve_normative_organ(name),
    )
    session.label_map[lid] = entry
    binary_masks[lid] = binary
    # Preview multi-class volume only fills empty voxels so user ROIs stay intact.
    session.labels[(binary > 0) & (session.labels == 0)] = lid
    occupied_names.add(key)
    return name


def build_dicom_seg_export_session(cache_dir: Path) -> AnnotateSession | None:
    """Build an in-memory annotate session for DICOM-SEG export.

    Combines user ROI labels (``annotations/``) with TotalSegmentator overlay
    masks under ``seg/`` (brain structures, organs, …). Does **not** write
    ``annotations/``. Face Blur masks are excluded. Returns None when there is
    no volume grid or no segment content to export.
    """
    cache_dir = Path(cache_dir)
    base = load_annotate_session(cache_dir)
    if base is None:
        return None

    session = AnnotateSession(
        cache_dir=base.cache_dir,
        labels=np.array(base.labels, copy=True, dtype=np.uint16),
        label_map=dict(base.label_map),
        reference_image=base.reference_image,
        ts_edits={name: np.array(mask, copy=True) for name, mask in base.ts_edits.items()},
    )
    occupied = {normalize_label_name(entry.name) for entry in session.label_map.values()}
    automatic_names: set[str] = set()
    binary_masks: dict[int, np.ndarray] = {}

    seg_dir = cache_dir / "seg"
    if seg_dir.is_dir():
        for path in sorted(seg_dir.glob("*.nii.gz")):
            stem = path.name[: -len(".nii.gz")]
            if stem in _FACE_MASK_STEMS:
                continue
            try:
                img = sitk.ReadImage(str(path))
                mask = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
            except RuntimeError as exc:
                logger.warning("Could not read TS mask %s: %s", path, exc)
                continue
            painted = _paint_binary_label(
                session, stem, mask, occupied_names=occupied, binary_masks=binary_masks
            )
            if painted:
                automatic_names.add(normalize_label_name(painted))

    # Prefer edited TS masks over raw ``seg/`` for the same structure name.
    for name, edit_mask in sorted(session.ts_edits.items()):
        key = normalize_label_name(name)
        if key in automatic_names:
            for lid, entry in list(session.label_map.items()):
                if normalize_label_name(entry.name) == key:
                    binary = (edit_mask > 0).astype(np.uint8)
                    if np.any(binary):
                        binary_masks[lid] = binary
                        session.labels[session.labels == lid] = 0
                        session.labels[binary > 0] = lid
                    break
            continue
        painted = _paint_binary_label(
            session, name, edit_mask, occupied_names=occupied, binary_masks=binary_masks
        )
        if painted:
            automatic_names.add(normalize_label_name(painted))

    if not np.any(session.labels > 0) and not binary_masks:
        return None

    session._dicom_seg_automatic_names = automatic_names  # type: ignore[attr-defined]
    session._dicom_seg_binary_masks = binary_masks  # type: ignore[attr-defined]
    return session


def _pack_binary_frames(frames: list[np.ndarray]) -> bytes:
    """Pack binary (0/1) HxW frames into DICOM bit-packed little-endian bytes."""
    if not frames:
        return b""
    packed_parts: list[bytes] = []
    for frame in frames:
        flat = (frame > 0).astype(np.uint8).ravel()
        # Pad to multiple of 8 bits
        pad = (-len(flat)) % 8
        if pad:
            flat = np.concatenate([flat, np.zeros(pad, dtype=np.uint8)])
        bits = np.packbits(flat, bitorder="little")
        packed_parts.append(bits.tobytes())
    return b"".join(packed_parts)


def _source_refs_from_series(series_dir: Path) -> tuple[Dataset | None, list[Dataset]]:
    """Return a template dataset and per-frame referenced SOP items when possible.

    Uses Series View frame order (stackable slices, or expanded multi-frame / planar
    listing) so ``zi`` aligns with label volume depth.
    """
    from pydicom import dcmread

    from anonymizer.controller.annotations.planar_geometry import annotation_source_dicom_paths

    try:
        paths = annotation_source_dicom_paths(series_dir)
    except Exception as exc:  # noqa: BLE001 — export best-effort
        logger.warning("Could not list series DICOMs for DICOM-SEG: %s", exc)
        return None, []

    template: Dataset | None = None
    refs: list[Dataset] = []
    for path in paths:
        try:
            ds = dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception:  # noqa: BLE001
            continue
        if template is None:
            template = ds
        item = Dataset()
        item.ReferencedSOPClassUID = str(getattr(ds, "SOPClassUID", "") or "")
        item.ReferencedSOPInstanceUID = str(getattr(ds, "SOPInstanceUID", "") or "")
        refs.append(item)
    return template, refs


def _build_referenced_series_sequence(template: Dataset | None, slice_refs: list[Dataset]) -> Sequence | None:
    """Common Instance Reference: one ReferencedSeriesSequence item for the source series."""
    if template is None or not slice_refs:
        return None
    series_uid = str(getattr(template, "SeriesInstanceUID", "") or "")
    if not series_uid:
        return None
    instances: list[Dataset] = []
    seen: set[str] = set()
    for ref in slice_refs:
        sop_uid = str(getattr(ref, "ReferencedSOPInstanceUID", "") or "")
        if not sop_uid or sop_uid in seen:
            continue
        seen.add(sop_uid)
        inst = Dataset()
        inst.ReferencedSOPClassUID = str(getattr(ref, "ReferencedSOPClassUID", "") or "")
        inst.ReferencedSOPInstanceUID = sop_uid
        instances.append(inst)
    if not instances:
        return None
    series_item = Dataset()
    series_item.SeriesInstanceUID = series_uid
    series_item.ReferencedInstanceSequence = Sequence(instances)
    return Sequence([series_item])


def _build_dimension_organization(dimension_organization_uid: str) -> tuple[Sequence, Sequence]:
    """Multi-frame dimension organization: Segment Number + Image Position Patient."""
    org = Dataset()
    org.DimensionOrganizationUID = dimension_organization_uid

    # Dimension 1: referenced segment number within Segment Identification Sequence
    dim_seg = Dataset()
    dim_seg.DimensionOrganizationUID = dimension_organization_uid
    dim_seg.DimensionIndexPointer = (0x0062, 0x000B)  # ReferencedSegmentNumber
    dim_seg.FunctionalGroupPointer = (0x0062, 0x000A)  # SegmentIdentificationSequence

    # Dimension 2: Image Position Patient within Plane Position Sequence
    dim_pos = Dataset()
    dim_pos.DimensionOrganizationUID = dimension_organization_uid
    dim_pos.DimensionIndexPointer = (0x0020, 0x0032)  # ImagePositionPatient
    dim_pos.FunctionalGroupPointer = (0x0020, 0x9113)  # PlanePositionSequence

    return Sequence([org]), Sequence([dim_seg, dim_pos])


def export_dicom_seg(
    cache_dir: Path,
    dest_path: Path,
    *,
    series_dir: Path | None = None,
    session: AnnotateSession | None = None,
) -> Path:
    """Write a DICOM Segmentation file from label volumes + label map.

    When ``session`` is omitted, builds one via :func:`build_dicom_seg_export_session`
    (user ROI annotations plus TotalSegmentator ``seg/`` masks).

    One segment per label_map entry. Frames are binary bit-packed axial slices that
    contain the label. Source series UIDs are referenced when ``series_dir`` is given.
    """
    cache_dir = Path(cache_dir)
    dest_path = Path(dest_path)
    if session is not None and session.dirty:
        save_annotate_session(session)
    if session is None:
        session = build_dicom_seg_export_session(cache_dir)
    if session is None:
        raise FileNotFoundError(f"No segment content available under {cache_dir}")
    if not session.label_map:
        # Still allow empty map if labels volume has ids — synthesize entries.
        present_ids = sorted({int(v) for v in np.unique(session.labels) if int(v) > 0})
        for lid in present_ids:
            session.label_map[lid] = LabelEntry(label_id=lid, name=f"label_{lid}", color_bgr=(0, 165, 255))

    automatic_names: set[str] = getattr(session, "_dicom_seg_automatic_names", set()) or set()
    binary_masks: dict[int, np.ndarray] = getattr(session, "_dicom_seg_binary_masks", {}) or {}
    has_automatic = bool(automatic_names)
    has_manual = any(
        normalize_label_name(entry.name) not in automatic_names for entry in session.label_map.values()
    )

    template, slice_refs = _source_refs_from_series(series_dir) if series_dir else (None, [])
    labels = session.labels
    z, rows, cols = labels.shape

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SegmentationStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    now = dt.datetime.now()
    ds = FileDataset(str(dest_path), {}, file_meta=file_meta, preamble=b"\0" * 128)

    ds.SOPClassUID = SegmentationStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "SEG"
    ds.ImageType = ["DERIVED", "PRIMARY"]
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = (
        str(getattr(template, "StudyInstanceUID", "") or "") if template is not None else generate_uid()
    )
    ds.FrameOfReferenceUID = (
        str(getattr(template, "FrameOfReferenceUID", "") or "") if template is not None else generate_uid()
    )
    ds.SeriesNumber = 9001
    ds.InstanceNumber = 1
    if has_automatic and has_manual:
        ds.ContentLabel = "SEGMENTS"
        ds.ContentDescription = "Anatomy segments and user ROI annotations"
        ds.SeriesDescription = "Segments + ROI Annotations"
    elif has_automatic:
        ds.ContentLabel = "ANATOMY_SEG"
        ds.ContentDescription = "TotalSegmentator anatomy segments"
        ds.SeriesDescription = "Anatomy Segments"
    else:
        ds.ContentLabel = "ROI_ANNOTATION"
        ds.ContentDescription = "User ROI annotations"
        ds.SeriesDescription = "ROI Annotations"
    ds.ContentCreatorName = "RSNA Anonymizer"
    ds.PatientName = str(getattr(template, "PatientName", "Anonymous") or "Anonymous") if template else "Anonymous"
    ds.PatientID = str(getattr(template, "PatientID", "ANON") or "ANON") if template else "ANON"
    ds.StudyDate = str(getattr(template, "StudyDate", now.strftime("%Y%m%d")) or now.strftime("%Y%m%d"))
    ds.StudyTime = str(getattr(template, "StudyTime", now.strftime("%H%M%S")) or now.strftime("%H%M%S"))
    ds.ContentDate = now.strftime("%Y%m%d")
    ds.ContentTime = now.strftime("%H%M%S")

    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = int(rows)
    ds.Columns = int(cols)
    ds.BitsAllocated = 1
    ds.BitsStored = 1
    ds.HighBit = 0
    ds.PixelRepresentation = 0
    ds.LossyImageCompression = "00"
    ds.SegmentationType = "BINARY"

    ref_series_seq = _build_referenced_series_sequence(template, slice_refs)
    if ref_series_seq is not None:
        ds.ReferencedSeriesSequence = ref_series_seq

    dimension_organization_uid = generate_uid()
    ds.DimensionOrganizationSequence, ds.DimensionIndexSequence = _build_dimension_organization(
        dimension_organization_uid
    )

    ref = session.reference_image
    shared = Dataset()
    pixel_measures = Dataset()
    if ref is not None:
        spacing = ref.GetSpacing()  # x, y, z
        pixel_measures.PixelSpacing = [float(spacing[1]), float(spacing[0])]
        pixel_measures.SliceThickness = float(spacing[2])
    else:
        pixel_measures.PixelSpacing = [1.0, 1.0]
        pixel_measures.SliceThickness = 1.0
    shared.PixelMeasuresSequence = Sequence([pixel_measures])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])

    segment_items: list[Dataset] = []
    for number, (lid, entry) in enumerate(sorted(session.label_map.items()), start=1):
        seg_item = Dataset()
        seg_item.SegmentNumber = number
        seg_item.SegmentLabel = entry.name[:64]
        seg_item.SegmentDescription = f"label_id={lid}"
        seg_item.SegmentAlgorithmType = (
            "AUTOMATIC" if normalize_label_name(entry.name) in automatic_names else "MANUAL"
        )
        cat = Dataset()
        cat.CodeValue = "T-D0050"
        cat.CodingSchemeDesignator = "SRT"
        cat.CodeMeaning = "Tissue"
        prop = Dataset()
        prop.CodeValue = "T-D0050"
        prop.CodingSchemeDesignator = "SRT"
        prop.CodeMeaning = entry.name[:64]
        seg_item.SegmentedPropertyCategoryCodeSequence = Sequence([cat])
        seg_item.SegmentedPropertyTypeCodeSequence = Sequence([prop])
        segment_items.append(seg_item)
    ds.SegmentSequence = Sequence(segment_items)

    # Build per-label per-slice frames
    frames: list[np.ndarray] = []
    per_frame: list[Dataset] = []
    label_id_to_number = {lid: n for n, (lid, _) in enumerate(sorted(session.label_map.items()), start=1)}

    for lid, _entry in sorted(session.label_map.items()):
        number = label_id_to_number[lid]
        lid_volume = binary_masks.get(lid)
        for zi in range(z):
            plane = lid_volume[zi] > 0 if lid_volume is not None else labels[zi] == lid
            if not np.any(plane):
                continue
            frames.append(plane.astype(np.uint8))
            fg = Dataset()
            frame_content = Dataset()
            # Matches DimensionIndexSequence order: segment number, 1-based stack position.
            frame_content.DimensionIndexValues = [int(number), int(zi) + 1]
            fg.FrameContentSequence = Sequence([frame_content])
            der = Dataset()
            der.ReferencedSegmentNumber = number
            fg.SegmentIdentificationSequence = Sequence([der])
            if zi < len(slice_refs):
                sop = Dataset()
                sop.ReferencedSOPClassUID = slice_refs[zi].ReferencedSOPClassUID
                sop.ReferencedSOPInstanceUID = slice_refs[zi].ReferencedSOPInstanceUID
                # DerivationImageSequence
                der_img = Dataset()
                src = Dataset()
                src.ReferencedSOPClassUID = sop.ReferencedSOPClassUID
                src.ReferencedSOPInstanceUID = sop.ReferencedSOPInstanceUID
                purpose = Dataset()
                purpose.CodeValue = "121322"
                purpose.CodingSchemeDesignator = "DCM"
                purpose.CodeMeaning = "Source image for image processing operation"
                src.PurposeOfReferenceCodeSequence = Sequence([purpose])
                der_img.SourceImageSequence = Sequence([src])
                fg.DerivationImageSequence = Sequence([der_img])
            # Plane position
            if ref is not None:
                # sitk index: (x, y, z) = (col, row, slice)
                phys = ref.TransformIndexToPhysicalPoint((0, 0, int(zi)))
                pos = Dataset()
                pos.ImagePositionPatient = [float(phys[0]), float(phys[1]), float(phys[2])]
                fg.PlanePositionSequence = Sequence([pos])
                direction = ref.GetDirection()
                # direction is 9-tuple row-major 3x3
                orient = Dataset()
                orient.ImageOrientationPatient = [
                    float(direction[0]),
                    float(direction[3]),
                    float(direction[6]),
                    float(direction[1]),
                    float(direction[4]),
                    float(direction[7]),
                ]
                fg.PlaneOrientationSequence = Sequence([orient])
            per_frame.append(fg)

    if not frames:
        # Empty SEG still valid with no frames — write minimal placeholder
        empty = np.zeros((rows, cols), dtype=np.uint8)
        frames = [empty]
        fg = Dataset()
        frame_content = Dataset()
        frame_content.DimensionIndexValues = [1, 1]
        fg.FrameContentSequence = Sequence([frame_content])
        der = Dataset()
        der.ReferencedSegmentNumber = 1
        fg.SegmentIdentificationSequence = Sequence([der])
        per_frame = [fg]

    ds.NumberOfFrames = str(len(frames))
    ds.PerFrameFunctionalGroupsSequence = Sequence(per_frame)
    ds.PixelData = _pack_binary_frames(frames)

    if template is not None:
        ds.ReferringPhysicianName = getattr(template, "ReferringPhysicianName", "")
        if hasattr(template, "StudyID"):
            ds.StudyID = template.StudyID

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(dest_path), enforce_file_format=True, little_endian=True, implicit_vr=False)
    logger.info(
        "Wrote DICOM-SEG %s frames=%d labels=%d labels_file=%s",
        dest_path,
        len(frames),
        len(session.label_map),
        labels_path(cache_dir),
    )
    return dest_path
