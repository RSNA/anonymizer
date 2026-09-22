"""DICOM Segmentation IOD export from multi-class label volumes."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import numpy as np
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
    labels_path,
    load_annotate_session,
    save_annotate_session,
)

logger = logging.getLogger(__name__)


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
    """Return a template dataset and per-slice referenced SOP items when possible."""
    from pydicom import dcmread

    from anonymizer.controller.ai.tseg.dicom_geometry import stackable_dicom_paths

    try:
        paths = stackable_dicom_paths(series_dir)
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


def export_dicom_seg(
    cache_dir: Path,
    dest_path: Path,
    *,
    series_dir: Path | None = None,
    session: AnnotateSession | None = None,
) -> Path:
    """Write a DICOM Segmentation file from ``labels.nii.gz`` + ``label_map.json``.

    One segment per label_map entry. Frames are binary bit-packed axial slices that
    contain the label. Source series UIDs are referenced when ``series_dir`` is given.
    """
    cache_dir = Path(cache_dir)
    dest_path = Path(dest_path)
    if session is not None and session.dirty:
        save_annotate_session(session)
    if session is None:
        session = load_annotate_session(cache_dir)
    if session is None:
        raise FileNotFoundError(f"No annotation session available under {cache_dir}")
    if not session.label_map:
        # Still allow empty map if labels volume has ids — synthesize entries.
        present_ids = sorted({int(v) for v in np.unique(session.labels) if int(v) > 0})
        for lid in present_ids:
            session.label_map[lid] = LabelEntry(label_id=lid, name=f"label_{lid}", color_bgr=(0, 165, 255))

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
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = (
        str(getattr(template, "StudyInstanceUID", "") or "") if template is not None else generate_uid()
    )
    ds.FrameOfReferenceUID = (
        str(getattr(template, "FrameOfReferenceUID", "") or "") if template is not None else generate_uid()
    )
    ds.SeriesNumber = 9001
    ds.InstanceNumber = 1
    ds.ContentLabel = "ROI_ANNOTATION"
    ds.ContentDescription = "User ROI annotations"
    ds.ContentCreatorName = "RSNA Anonymizer"
    ds.SeriesDescription = "ROI Annotations"
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
    ds.MaximumFractionalValue = 1

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
        seg_item.SegmentAlgorithmType = "MANUAL"
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
        for zi in range(z):
            plane = labels[zi] == lid
            if not np.any(plane):
                continue
            frames.append(plane.astype(np.uint8))
            fg = Dataset()
            der = Dataset()
            der.SegmentNumber = number
            fg.SegmentIdentificationSequence = Sequence([der])
            if zi < len(slice_refs):
                ref_img = Dataset()
                ref_series = Dataset()
                if template is not None:
                    ref_series.SeriesInstanceUID = str(getattr(template, "SeriesInstanceUID", "") or "")
                sop = Dataset()
                sop.ReferencedSOPClassUID = slice_refs[zi].ReferencedSOPClassUID
                sop.ReferencedSOPInstanceUID = slice_refs[zi].ReferencedSOPInstanceUID
                ref_series.ReferencedSOPSequence = Sequence([sop])
                ref_img.ReferencedImageSequence = Sequence([sop])
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
                # Index as x,y,z physical from SimpleITK
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
        der = Dataset()
        der.SegmentNumber = 1
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
