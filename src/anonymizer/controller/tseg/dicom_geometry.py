"""DICOM series geometry: acquisition plane, 2D/3D dimensionality, and provenance.

Used by the tseg pipeline and Harmonize to sort slices correctly, cache metadata under
``A_TS_SEG/geometry.json``, and decide whether TotalSegmentator should run.
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import SimpleITK as sitk
from pydicom import Dataset, dcmread

from anonymizer.controller.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.tseg.config import (
    GEOMETRY_CACHE_FILENAME,
    LOCALIZER_MAX_SLICES,
    MIN_DICOM_SLICES,
    MIN_THROUGH_PLANE_EXTENT_MM,
    OBLIQUE_DOT_THRESHOLD,
    PLANE_AMBIGUITY_DOT_DELTA,
)
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

PlaneLabel = Literal["axial", "sagittal", "coronal", "oblique", "unknown"]
DimensionalityLabel = Literal[
    "volume_3d",
    "localizer_2d",
    "single_slice_2d",
    "multiframe_volume",
    "projection_2d",
    "unknown",
]
ProvenanceLabel = Literal[
    "original",
    "derived_reformat",
    "derived_3d_render",
    "derived_secondary",
    "unknown",
]

PLANE_AXES_LPS: dict[str, tuple[float, float, float]] = {
    "axial": (0.0, 0.0, 1.0),
    "coronal": (0.0, 1.0, 0.0),
    "sagittal": (1.0, 0.0, 0.0),
}

MPR_KEYWORDS = ("MPR", "REFORMAT", "REFORMATTED", "OBLIQUE", "CURVED")
RENDER_KEYWORDS = ("MIP", "MINIP", "VR", "VRT", "3D", "SSD", "AVERAGE", "THICK SLAB")
LOCALIZER_KEYWORDS = ("SCOUT", "TOPO", "TOPOGRAM", "SCANOGRAM", "LOCALIZER", "SURVIEW", "PLAN")

SECONDARY_CAPTURE_SOP = "1.2.840.10008.5.1.4.1.1.7"
IMAGE_STORAGE_SOP_PREFIX = "1.2.840.10008.5.1.4.1.1."
NON_STACKABLE_SOP_PREFIXES = (
    "1.2.840.10008.5.1.4.1.1.88",  # Structured Report
    "1.2.840.10008.5.1.4.1.1.104",  # Encapsulated PDF
)


@dataclass(frozen=True)
class StackMetrics:
    n_slices: int
    slice_spacing_mm: float | None
    through_plane_extent_mm: float | None
    spacing_regularity: float | None


@dataclass(frozen=True)
class SeriesGeometryResult:
    plane: PlaneLabel
    plane_confidence: float
    slice_normal_lps: tuple[float, float, float] | None
    plane_angles_deg: dict[str, float]

    dimensionality: DimensionalityLabel
    n_slices: int
    through_plane_extent_mm: float | None
    slice_spacing_mm: float | None
    spacing_regularity: float | None

    provenance: ProvenanceLabel
    provenance_confidence: float
    image_type: tuple[str, ...] | None
    source_series_uids: tuple[str, ...]

    ts_suitable: bool
    metadata_suspect: bool
    method: str
    notes: str


def _looks_like_dicom(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".dcm") or name.endswith(".dicom") or "." not in path.name


def list_dicom_paths(series_directory: Path) -> list[Path]:
    series_directory = Path(series_directory)
    paths = [
        path
        for path in series_directory.iterdir()
        if path.is_file() and not path.name.startswith(".") and _looks_like_dicom(path)
    ]
    if not paths:
        raise ValueError(f"No DICOM files found in {series_directory}")
    return paths


def _vector3(values) -> tuple[float, float, float]:
    if values is None or len(values) < 3:
        raise ValueError(f"Expected 3-vector, got {values!r}")
    return (float(values[0]), float(values[1]), float(values[2]))


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= 1e-8:
        raise ValueError(f"Zero-length vector: {vector}")
    return tuple(component / magnitude for component in vector)


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def slice_normal_from_iop(image_orientation_patient) -> tuple[float, float, float]:
    """Slice normal in patient LPS from ``ImageOrientationPatient`` (6 values)."""
    values = [float(value) for value in image_orientation_patient]
    if len(values) != 6:
        raise ValueError(f"ImageOrientationPatient must have 6 values, got {len(values)}")
    row = _vector3(values[:3])
    column = _vector3(values[3:])
    return _normalize(_cross(row, column))


def project_ipp_onto_normal(
    image_position_patient,
    slice_normal: tuple[float, float, float],
) -> float:
    """Scalar position of an instance along the slice stack direction."""
    ipp = _vector3(image_position_patient)
    return _dot(ipp, slice_normal)


def classify_plane(
    slice_normal: tuple[float, float, float],
    *,
    oblique_threshold: float = OBLIQUE_DOT_THRESHOLD,
    ambiguity_delta: float = PLANE_AMBIGUITY_DOT_DELTA,
) -> tuple[PlaneLabel, float, dict[str, float]]:
    """Classify acquisition plane from a unit slice normal in LPS."""
    normal = _normalize(slice_normal)
    dots = {name: abs(_dot(normal, axis)) for name, axis in PLANE_AXES_LPS.items()}
    angles_deg = {name: math.degrees(math.acos(min(max(dot, -1.0), 1.0))) for name, dot in dots.items()}
    ranked = sorted(dots.items(), key=lambda item: item[1], reverse=True)
    best_plane, best_dot = ranked[0]
    second_dot = ranked[1][1]

    if best_dot < oblique_threshold:
        return "oblique", best_dot, angles_deg
    if second_dot >= oblique_threshold and (best_dot - second_dot) < ambiguity_delta:
        return "oblique", best_dot, angles_deg
    return best_plane, best_dot, angles_deg


def _normalized_text(*parts: str | None) -> str:
    return " ".join(part.strip().upper() for part in parts if part and str(part).strip())


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _image_type_values(header: Dataset) -> tuple[str, ...] | None:
    image_type = getattr(header, "ImageType", None)
    if image_type is None:
        return None
    return tuple(str(value).upper() for value in image_type)


def _referenced_series_uids(header: Dataset) -> tuple[str, ...]:
    uids: list[str] = []
    sequence = getattr(header, "ReferencedSeriesSequence", None)
    if sequence is None:
        return ()
    for item in sequence:
        uid = getattr(item, "SeriesInstanceUID", None)
        if uid:
            uids.append(str(uid))
    return tuple(uids)


def infer_provenance(
    headers: list[Dataset],
    *,
    series_description: str | None = None,
    protocol_name: str | None = None,
    derivation_description: str | None = None,
) -> tuple[ProvenanceLabel, float, tuple[str, ...] | None, tuple[str, ...]]:
    """Infer original vs derived provenance from DICOM headers."""
    if not headers:
        return "unknown", 0.0, None, ()

    header = headers[0]
    image_type = _image_type_values(header)
    description_text = _normalized_text(
        series_description or getattr(header, "SeriesDescription", None),
        protocol_name or getattr(header, "ProtocolName", None),
        derivation_description or getattr(header, "DerivationDescription", None),
    )
    source_uids = _referenced_series_uids(header)

    if image_type:
        primary = image_type[0] if image_type else ""
        if primary == "ORIGINAL":
            confidence = 0.95 if "PRIMARY" in image_type else 0.85
            return "original", confidence, image_type, source_uids
        if primary == "DERIVED":
            if _contains_keyword(description_text, RENDER_KEYWORDS):
                return "derived_3d_render", 0.9, image_type, source_uids
            if _contains_keyword(description_text, MPR_KEYWORDS) or source_uids:
                return "derived_reformat", 0.85, image_type, source_uids
            return "derived_secondary", 0.75, image_type, source_uids

    if source_uids:
        return "derived_reformat", 0.7, image_type, source_uids
    if _contains_keyword(description_text, RENDER_KEYWORDS):
        return "derived_3d_render", 0.65, image_type, source_uids
    if _contains_keyword(description_text, MPR_KEYWORDS):
        return "derived_reformat", 0.65, image_type, source_uids
    if description_text:
        return "original", 0.5, image_type, source_uids
    return "unknown", 0.0, image_type, source_uids


def compute_stack_metrics(
    headers: list[Dataset],
    slice_normal: tuple[float, float, float] | None,
) -> StackMetrics:
    """Compute slice count, spacing, extent, and regularity along the stack direction."""
    n_slices = len(headers)
    if n_slices == 0:
        return StackMetrics(0, None, None, None)

    if slice_normal is None or n_slices == 1:
        spacing = float(getattr(headers[0], "SliceThickness", 0.0) or 0.0) or None
        extent = spacing if n_slices == 1 and spacing else None
        return StackMetrics(n_slices, spacing, extent, None)

    positions = [
        project_ipp_onto_normal(header.ImagePositionPatient, slice_normal)
        for header in headers
        if getattr(header, "ImagePositionPatient", None) is not None
    ]
    if len(positions) < 2:
        spacing = float(getattr(headers[0], "SliceThickness", 0.0) or 0.0) or None
        return StackMetrics(n_slices, spacing, None, None)

    positions.sort()
    steps = [abs(positions[index + 1] - positions[index]) for index in range(len(positions) - 1)]
    positive_steps = [step for step in steps if step > 1e-6]
    if not positive_steps:
        spacing = float(getattr(headers[0], "SliceThickness", 0.0) or 0.0) or None
        return StackMetrics(n_slices, spacing, 0.0, 0.0)

    mean_step = sum(positive_steps) / len(positive_steps)
    variance = sum((step - mean_step) ** 2 for step in positive_steps) / len(positive_steps)
    std_dev = math.sqrt(variance)
    regularity = max(0.0, 1.0 - (std_dev / mean_step if mean_step > 0 else 1.0))
    extent = mean_step * (len(positions) - 1)
    return StackMetrics(n_slices, mean_step, extent, regularity)


def infer_dimensionality(
    headers: list[Dataset],
    stack: StackMetrics,
    *,
    series_description: str | None = None,
) -> DimensionalityLabel:
    """Classify whether the series is a diagnostic volume, localizer, or single-slice 2D."""
    if not headers:
        return "unknown"

    header = headers[0]
    description_text = _normalized_text(
        series_description or getattr(header, "SeriesDescription", None),
        getattr(header, "ProtocolName", None),
    )
    image_type = _image_type_values(header)
    sop_class = str(getattr(header, "SOPClassUID", ""))

    if sop_class == SECONDARY_CAPTURE_SOP:
        return "projection_2d"

    number_of_frames = int(getattr(header, "NumberOfFrames", 1) or 1)
    if number_of_frames > 1 and stack.n_slices == 1:
        return "multiframe_volume"

    if stack.n_slices <= 1:
        return "single_slice_2d"

    if image_type and any(token in image_type for token in ("LOCALIZER", "SCOUT", "TOPOGRAM")):
        return "localizer_2d"
    if _contains_keyword(description_text, LOCALIZER_KEYWORDS):
        return "localizer_2d"

    if stack.n_slices >= MIN_DICOM_SLICES:
        return "volume_3d"

    if stack.n_slices <= LOCALIZER_MAX_SLICES:
        extent = stack.through_plane_extent_mm or 0.0
        if extent < MIN_THROUGH_PLANE_EXTENT_MM:
            return "localizer_2d"

    return "unknown"


def ts_regions_eligible(geometry: SeriesGeometryResult) -> bool:
    """Return True when TotalSegmentator anatomy segmentation should run."""
    return geometry.ts_suitable


def _build_ts_suitable(
    dimensionality: DimensionalityLabel,
    provenance: ProvenanceLabel,
) -> tuple[bool, str]:
    if dimensionality in {"localizer_2d", "single_slice_2d", "projection_2d"}:
        return False, f"Not a diagnostic 3D volume ({dimensionality})"
    if dimensionality == "unknown":
        return False, "Could not classify series dimensionality"
    if provenance == "derived_3d_render":
        return False, "Derived 3D render (MIP/VR) is not suitable for organ segmentation"
    if dimensionality in {"volume_3d", "multiframe_volume"}:
        return True, ""
    return False, f"Unsupported dimensionality: {dimensionality}"


def read_series_headers(series_directory: Path) -> list[Dataset]:
    """Load DICOM headers (no pixels) for all instances in a series directory."""
    paths = list_dicom_paths(series_directory)
    return [dcmread(path, stop_before_pixels=True) for path in paths]


def _slice_rows_columns(header: Dataset) -> tuple[int, int] | None:
    rows = getattr(header, "Rows", None)
    cols = getattr(header, "Columns", None)
    if rows is None or cols is None:
        return None
    return int(rows), int(cols)


def _format_slice_dimension_ref(path: Path, header: Dataset, dims: tuple[int, int] | None) -> str:
    instance = getattr(header, "InstanceNumber", None)
    instance_text = str(instance) if instance is not None else "?"
    if dims is None:
        return f"{path.name} (missing Rows/Columns, InstanceNumber={instance_text})"
    return f"{path.name}={dims[0]}x{dims[1]} (InstanceNumber={instance_text})"


def validate_uniform_slice_dimensions(
    paths: list[Path],
    headers: list[Dataset],
    *,
    max_listed: int = 20,
) -> str | None:
    """
    Return None when all slices share the same Rows/Columns.

    Otherwise return a precise rejection message listing inconsistent slices
    (and any slices missing Rows/Columns).
    """
    if len(paths) != len(headers):
        raise ValueError("paths and headers must have the same length")
    if not paths:
        return None

    sized: list[tuple[Path, Dataset, tuple[int, int] | None]] = [
        (path, header, _slice_rows_columns(header)) for path, header in zip(paths, headers, strict=True)
    ]
    present = [(path, header, dims) for path, header, dims in sized if dims is not None]
    missing = [(path, header) for path, header, dims in sized if dims is None]

    counts = Counter(dims for _, _, dims in present)
    if len(counts) <= 1 and not missing:
        return None

    if present:
        (canonical, n_canonical) = counts.most_common(1)[0]
        outliers = [(path, header, dims) for path, header, dims in present if dims != canonical]
        message = (
            f"Non-uniform Rows/Columns across series: majority {canonical[0]}x{canonical[1]} "
            f"({n_canonical}/{len(present)} slices with size tags)"
        )
    else:
        outliers = []
        message = "Non-uniform Rows/Columns across series: no slices have Rows and Columns"

    if outliers:
        shown = outliers[:max_listed]
        listed = ", ".join(_format_slice_dimension_ref(path, header, dims) for path, header, dims in shown)
        remainder = len(outliers) - len(shown)
        if remainder > 0:
            listed = f"{listed}, ... and {remainder} more"
        message = f"{message}; inconsistent: {listed}"

    if missing:
        shown_missing = missing[:max_listed]
        listed_missing = ", ".join(
            _format_slice_dimension_ref(path, header, None) for path, header in shown_missing
        )
        remainder = len(missing) - len(shown_missing)
        if remainder > 0:
            listed_missing = f"{listed_missing}, ... and {remainder} more"
        message = f"{message}; missing size: {listed_missing}"

    return message


def sorted_dicom_paths(series_directory: Path) -> list[Path]:
    """Return DICOM paths sorted along the acquisition stack direction."""
    paths = list_dicom_paths(series_directory)
    first_header = dcmread(paths[0], stop_before_pixels=True)
    try:
        slice_normal = slice_normal_from_iop(first_header.ImageOrientationPatient)
    except (AttributeError, TypeError, ValueError):
        logger.warning(
            "Falling back to ImagePositionPatient[2] sort for %s (missing or invalid IOP)",
            series_directory,
        )
        return sorted(
            paths,
            key=lambda path: float(dcmread(path, stop_before_pixels=True).ImagePositionPatient[2]),
        )

    return sorted(
        paths,
        key=lambda path: project_ipp_onto_normal(
            dcmread(path, stop_before_pixels=True).ImagePositionPatient,
            slice_normal,
        ),
    )


def is_stackable_image_header(header: Dataset) -> bool:
    """Return True when a lightweight header describes one grayscale/stackable slice."""
    sop_class = str(getattr(header, "SOPClassUID", "") or "")
    if not sop_class.startswith(IMAGE_STORAGE_SOP_PREFIX):
        return False
    if sop_class == SECONDARY_CAPTURE_SOP or any(
        sop_class.startswith(prefix) for prefix in NON_STACKABLE_SOP_PREFIXES
    ):
        return False
    rows = int(getattr(header, "Rows", 0) or 0)
    cols = int(getattr(header, "Columns", 0) or 0)
    if rows < 1 or cols < 1:
        return False
    if getattr(header, "PhotometricInterpretation", None) is None:
        return False
    if getattr(header, "BitsAllocated", None) is None:
        return False
    if int(getattr(header, "NumberOfFrames", 1) or 1) > 1:
        return False
    if getattr(header, "ImageOrientationPatient", None) is None:
        return False
    return getattr(header, "ImagePositionPatient", None) is not None


def stackable_dicom_paths(series_directory: Path) -> list[Path]:
    """
    Return stackable image slice paths sorted along the acquisition direction.

    Excludes non-image DICOM objects and stray instances from other series that
    sometimes appear in the same directory.
    """
    series_directory = Path(series_directory).resolve()
    entries: list[tuple[Path, Dataset]] = []
    for path in list_dicom_paths(series_directory):
        try:
            header = dcmread(path, stop_before_pixels=True, force=True)
        except Exception as exc:
            logger.warning("Skipping unreadable DICOM header %s: %s", path.name, exc)
            continue
        if not is_stackable_image_header(header):
            logger.debug(
                "Skipping non-stackable DICOM %s (SOPClassUID=%s)",
                path.name,
                getattr(header, "SOPClassUID", ""),
            )
            continue
        entries.append((path, header))

    if not entries:
        raise ValueError(f"No stackable image slices found in {series_directory}")

    series_uids = Counter(
        str(header.get("SeriesInstanceUID", "") or "")
        for _, header in entries
        if header.get("SeriesInstanceUID")
    )
    if len(series_uids) > 1:
        dominant_uid = series_uids.most_common(1)[0][0]
        excluded = sum(
            1 for _, header in entries if str(header.get("SeriesInstanceUID", "") or "") != dominant_uid
        )
        if excluded:
            logger.warning(
                "Excluding %d DICOM instance(s) with non-dominant SeriesInstanceUID in %s",
                excluded,
                series_directory,
            )
        entries = [
            (path, header)
            for path, header in entries
            if str(header.get("SeriesInstanceUID", "") or "") == dominant_uid
        ]

    path_by_sop = {str(header.SOPInstanceUID): path for path, header in entries}
    ordered_headers = headers_in_stack_order([header for _, header in entries])
    ordered_paths = [path_by_sop[str(header.SOPInstanceUID)] for header in ordered_headers]
    return ordered_paths


def _slice_spacing_mm_from_headers(headers: Sequence[Dataset]) -> float:
    first = headers[0]
    fallback = float(getattr(first, "SliceThickness", 1.0) or 1.0)
    if len(headers) < 2:
        return fallback
    try:
        slice_normal = slice_normal_from_iop(first.ImageOrientationPatient)
        positions = sorted(
            project_ipp_onto_normal(header.ImagePositionPatient, slice_normal) for header in headers
        )
        steps = [abs(positions[index + 1] - positions[index]) for index in range(len(positions) - 1)]
        positive_steps = [step for step in steps if step > 1e-6]
        if positive_steps:
            return sum(positive_steps) / len(positive_steps)
    except (AttributeError, TypeError, ValueError):
        pass
    return fallback


def _dicom_slice_has_pixel_data(path: Path) -> bool:
    """Return True when a DICOM instance contains decodable pixel data."""
    try:
        ds = dcmread(str(path), force=True)
    except Exception:
        return False
    if hasattr(ds, "PixelData") or hasattr(ds, "FloatPixelData") or hasattr(ds, "DoubleFloatPixelData"):
        try:
            _ = ds.pixel_array
        except (AttributeError, ValueError, TypeError):
            return False
        return True
    return False


def filter_dicom_paths_with_pixel_data(paths: Sequence[Path]) -> list[Path]:
    """Keep only stackable slice paths whose pixel data can be decoded."""
    readable: list[Path] = []
    for path in paths:
        if _dicom_slice_has_pixel_data(path):
            readable.append(Path(path))
    return readable


def build_sitk_volume_from_series_frames(
    reference_ds: Dataset,
    frames: np.ndarray,
    slice_paths: Sequence[Path],
    *,
    slice_spacing_mm: float | None = None,
) -> sitk.Image:
    """
    Build a 3D SimpleITK volume from a ``load_series_frames`` stack.

    Uses the same geometry tags as ``build_sitk_volume_from_pydicom`` so TS and face blur
    align with Series View pixels (modality LUT, MONOCHROME1 inversion, resize).
    """
    paths = tuple(Path(path) for path in slice_paths)
    if frames.ndim != 3:
        raise ValueError(f"Expected grayscale slice stack (Z, Y, X), got shape {frames.shape}")
    if frames.shape[0] != len(paths):
        raise ValueError(f"Frame count {frames.shape[0]} != slice path count {len(paths)}")

    first = reference_ds
    row_spacing, col_spacing = (float(value) for value in first.PixelSpacing)

    image = sitk.GetImageFromArray(np.asarray(frames))
    if slice_spacing_mm is not None and slice_spacing_mm > 0:
        spacing_z = float(slice_spacing_mm)
    else:
        headers = [dcmread(path, stop_before_pixels=True, force=True) for path in paths]
        spacing_z = _slice_spacing_mm_from_headers(headers)
    iop = [float(value) for value in first.ImageOrientationPatient]
    row_direction = iop[:3]
    column_direction = iop[3:]
    slice_direction = list(_cross(_vector3(row_direction), _vector3(column_direction)))

    image.SetSpacing((col_spacing, row_spacing, spacing_z))
    image.SetOrigin([float(value) for value in first.ImagePositionPatient])
    image.SetDirection(tuple(row_direction + column_direction + slice_direction))
    return image


def build_sitk_volume_from_pydicom(slice_paths: Sequence[Path]) -> sitk.Image:
    """Assemble a 3D SimpleITK volume from per-slice pydicom reads (same decoder path as Series View)."""
    paths = tuple(Path(path) for path in slice_paths)
    if not paths:
        raise ValueError("No DICOM slice paths provided")

    readable_paths: list[Path] = []
    for path in paths:
        if _dicom_slice_has_pixel_data(path):
            readable_paths.append(path)
        else:
            logger.warning("Skipping DICOM slice without pixel data: %s", path.name)

    if not readable_paths:
        raise ValueError("No DICOM slices with pixel data found")

    headers = [dcmread(path, stop_before_pixels=True, force=True) for path in readable_paths]
    first = headers[0]
    row_spacing, col_spacing = (float(value) for value in first.PixelSpacing)

    arrays: list[np.ndarray] = []
    for path in readable_paths:
        ds = dcmread(str(path), force=True)
        pixels = ds.pixel_array
        if pixels.ndim > 2:
            pixels = pixels[0]
        arrays.append(np.asarray(pixels))

    stack = np.stack(arrays, axis=0)
    image = sitk.GetImageFromArray(stack)

    slice_spacing = _slice_spacing_mm_from_headers(headers)
    iop = [float(value) for value in first.ImageOrientationPatient]
    row_direction = iop[:3]
    column_direction = iop[3:]
    slice_direction = list(_cross(_vector3(row_direction), _vector3(column_direction)))

    image.SetSpacing((col_spacing, row_spacing, slice_spacing))
    image.SetOrigin([float(value) for value in first.ImagePositionPatient])
    image.SetDirection(tuple(row_direction + column_direction + slice_direction))
    return image


def read_sitk_volume_from_dicom_paths(slice_paths: Sequence[Path]) -> sitk.Image:
    """
    Load a DICOM stack into SimpleITK using pydicom per-slice reads.

    Series View already loads the same slices via pydicom (``load_series_frames``).
    SimpleITK ``ImageSeriesReader`` can fail on transfer syntaxes or instances that
    pydicom decodes fine, so we prefer the pydicom path for consistency.
    """
    paths = tuple(Path(path) for path in slice_paths)
    if not paths:
        raise ValueError("No DICOM slice paths provided")
    return build_sitk_volume_from_pydicom(paths)


def headers_in_stack_order(headers: list[Dataset]) -> list[Dataset]:
    """Sort loaded headers along the slice normal derived from the first instance."""
    if not headers:
        return []
    try:
        slice_normal = slice_normal_from_iop(headers[0].ImageOrientationPatient)
        return sorted(
            headers,
            key=lambda header: project_ipp_onto_normal(header.ImagePositionPatient, slice_normal),
        )
    except (AttributeError, TypeError, ValueError):
        return sorted(
            headers,
            key=lambda header: float(header.ImagePositionPatient[2]),
        )


def _unknown_geometry_result(notes: str) -> SeriesGeometryResult:
    return SeriesGeometryResult(
        plane="unknown",
        plane_confidence=0.0,
        slice_normal_lps=None,
        plane_angles_deg={},
        dimensionality="unknown",
        n_slices=0,
        through_plane_extent_mm=None,
        slice_spacing_mm=None,
        spacing_regularity=None,
        provenance="unknown",
        provenance_confidence=0.0,
        image_type=None,
        source_series_uids=(),
        ts_suitable=False,
        metadata_suspect=True,
        method="none",
        notes=notes,
    )


def analyze_series_geometry(series_directory: Path) -> SeriesGeometryResult:
    """Infer plane, dimensionality, and provenance for one DICOM series directory."""
    series_directory = Path(series_directory).resolve()
    try:
        paths = list_dicom_paths(series_directory)
        raw_headers = [dcmread(path, stop_before_pixels=True) for path in paths]
    except ValueError as exc:
        return _unknown_geometry_result(str(exc))

    dimension_error = validate_uniform_slice_dimensions(paths, raw_headers)
    headers = headers_in_stack_order(raw_headers)

    slice_normal: tuple[float, float, float] | None = None
    plane: PlaneLabel = "unknown"
    plane_confidence = 0.0
    plane_angles_deg: dict[str, float] = {}
    metadata_suspect = dimension_error is not None
    method = "dicom_iop"

    try:
        slice_normal = slice_normal_from_iop(headers[0].ImageOrientationPatient)
        plane, plane_confidence, plane_angles_deg = classify_plane(slice_normal)
    except (AttributeError, TypeError, ValueError) as exc:
        metadata_suspect = True
        method = "fallback"
        logger.warning("Could not classify plane for %s: %s", series_directory, exc)

    stack = compute_stack_metrics(headers, slice_normal)
    provenance, provenance_confidence, image_type, source_uids = infer_provenance(headers)
    dimensionality = infer_dimensionality(headers, stack)
    ts_suitable, notes = _build_ts_suitable(dimensionality, provenance)

    if dimension_error is not None:
        # Mixed matrix sizes cannot be stacked by SimpleITK ImageSeriesReader.
        ts_suitable = False
        metadata_suspect = True
        notes = dimension_error
        logger.warning("Rejecting series for TS (%s): %s", series_directory, dimension_error)
    elif metadata_suspect and ts_suitable:
        notes = notes or "Plane classification unavailable; TS may be unreliable"

    return SeriesGeometryResult(
        plane=plane,
        plane_confidence=plane_confidence,
        slice_normal_lps=slice_normal,
        plane_angles_deg=plane_angles_deg,
        dimensionality=dimensionality,
        n_slices=stack.n_slices,
        through_plane_extent_mm=stack.through_plane_extent_mm,
        slice_spacing_mm=stack.slice_spacing_mm,
        spacing_regularity=stack.spacing_regularity,
        provenance=provenance,
        provenance_confidence=provenance_confidence,
        image_type=image_type,
        source_series_uids=source_uids,
        ts_suitable=ts_suitable,
        metadata_suspect=metadata_suspect,
        method=method,
        notes=notes,
    )


def tseg_cache_dir(series_directory: Path) -> Path:
    return resolve_series_cache_dir(series_directory)


def geometry_cache_path(series_directory: Path) -> Path:
    return tseg_cache_dir(series_directory) / GEOMETRY_CACHE_FILENAME


def geometry_to_dict(geometry: SeriesGeometryResult) -> dict:
    payload = asdict(geometry)
    payload["image_type"] = list(geometry.image_type) if geometry.image_type else None
    payload["source_series_uids"] = list(geometry.source_series_uids)
    if geometry.slice_normal_lps is not None:
        payload["slice_normal_lps"] = list(geometry.slice_normal_lps)
    return payload


def geometry_from_dict(payload: dict) -> SeriesGeometryResult:
    image_type = payload.get("image_type")
    source_uids = payload.get("source_series_uids") or ()
    slice_normal = payload.get("slice_normal_lps")
    return SeriesGeometryResult(
        plane=payload["plane"],
        plane_confidence=float(payload["plane_confidence"]),
        slice_normal_lps=tuple(slice_normal) if slice_normal is not None else None,
        plane_angles_deg={key: float(value) for key, value in payload.get("plane_angles_deg", {}).items()},
        dimensionality=payload["dimensionality"],
        n_slices=int(payload["n_slices"]),
        through_plane_extent_mm=payload.get("through_plane_extent_mm"),
        slice_spacing_mm=payload.get("slice_spacing_mm"),
        spacing_regularity=payload.get("spacing_regularity"),
        provenance=payload["provenance"],
        provenance_confidence=float(payload["provenance_confidence"]),
        image_type=tuple(image_type) if image_type else None,
        source_series_uids=tuple(source_uids),
        ts_suitable=bool(payload["ts_suitable"]),
        metadata_suspect=bool(payload.get("metadata_suspect", False)),
        method=str(payload.get("method", "cached")),
        notes=str(payload.get("notes", "")),
    )


def write_geometry_cache(series_directory: Path, geometry: SeriesGeometryResult) -> Path:
    cache_path = geometry_cache_path(series_directory)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(geometry_to_dict(geometry), indent=2), encoding="utf-8")
    return cache_path


def load_geometry_cache(series_directory: Path) -> SeriesGeometryResult | None:
    cache_path = geometry_cache_path(series_directory)
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return geometry_from_dict(payload)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring invalid geometry cache %s: %s", cache_path, exc)
        return None


# User-facing labels (msgids for gettext). Internal codes remain on SeriesGeometryResult.
_PROVENANCE_MSGIDS: dict[ProvenanceLabel, str] = {
    "original": "Original acquisition",
    "derived_reformat": "Reformatted series",
    "derived_3d_render": "3D rendering (MIP/VR)",
    "derived_secondary": "Derived secondary capture",
    "unknown": "Unknown source",
}

_PLANE_MSGIDS: dict[PlaneLabel, str] = {
    "axial": "Axial",
    "sagittal": "Sagittal",
    "coronal": "Coronal",
    "oblique": "Oblique",
    "unknown": "Unknown orientation",
}

_DIMENSIONALITY_MSGIDS: dict[DimensionalityLabel, str] = {
    "volume_3d": "Diagnostic 3D volume",
    "multiframe_volume": "Multi-frame volume",
    "localizer_2d": "Localizer or scout",
    "single_slice_2d": "Single slice",
    "projection_2d": "2D projection",
    "unknown": "Unknown series type",
}


def provenance_label(provenance: ProvenanceLabel) -> str:
    return _(_PROVENANCE_MSGIDS.get(provenance, "Unknown source"))


def plane_label(plane: PlaneLabel) -> str:
    return _(_PLANE_MSGIDS.get(plane, "Unknown orientation"))


def dimensionality_label(dimensionality: DimensionalityLabel) -> str:
    return _(_DIMENSIONALITY_MSGIDS.get(dimensionality, "Unknown series type"))


def ts_suitability_label(ts_suitable: bool) -> str:
    if ts_suitable:
        return _("Suitable for segmentation and anatomy analysis")
    return _("Not suitable for segmentation and anatomy analysis")


def geometry_skip_reason_label(geometry: SeriesGeometryResult) -> str:
    """Plain-language reason anatomy segmentation is unavailable."""
    if geometry.dimensionality == "localizer_2d":
        return _("Localizer and scout series are not suitable for anatomy analysis")
    if geometry.dimensionality == "single_slice_2d":
        return _("Single-slice series are not suitable for anatomy analysis")
    if geometry.dimensionality == "projection_2d":
        return _("Projection images are not suitable for anatomy analysis")
    if geometry.provenance == "derived_3d_render":
        return _("3D renderings (MIP or VR) are not suitable for anatomy analysis")
    if geometry.dimensionality == "unknown":
        return _("Series type could not be determined for anatomy analysis")
    return _("This series is not suitable for anatomy analysis")


def geometry_analysis_progress_prefix() -> str:
    return _("Geometry analysis") + ": "


def format_geometry_summary(geometry: SeriesGeometryResult) -> str:
    """Compact one-line summary for projection tiles and cached geometry captions."""
    ts_tag = "TS ok" if geometry.ts_suitable else "TS skip"
    return f"{geometry.plane} · {geometry.dimensionality} · {ts_tag}"


def format_series_view_geometry_line(geometry: SeriesGeometryResult) -> str:
    """Detailed one-line geometry caption for Series View row 2."""
    return (
        f"{_('Provenance')}: {provenance_label(geometry.provenance)} · "
        f"{_('Geometry')}: {plane_label(geometry.plane)} · "
        f"{dimensionality_label(geometry.dimensionality)} · "
        f"{ts_suitability_label(geometry.ts_suitable)} ·"
    )


def format_geometry_progress_message(geometry: SeriesGeometryResult) -> str:
    """Progress/status text after geometry analysis in Harmonize."""
    summary = format_geometry_summary(geometry)
    if not geometry.ts_suitable:
        return f"{geometry_analysis_progress_prefix()}{summary} — {geometry_skip_reason_label(geometry)}"
    return f"{geometry_analysis_progress_prefix()}{summary}"


def resolve_series_geometry(
    series_directory: Path,
    *,
    use_cache: bool = True,
    write_cache: bool = True,
) -> SeriesGeometryResult:
    """Load cached geometry or analyze headers and optionally persist to ``A_TS_SEG/geometry.json``."""
    series_directory = Path(series_directory).resolve()
    if use_cache:
        cached = load_geometry_cache(series_directory)
        if cached is not None:
            return cached

    geometry = analyze_series_geometry(series_directory)
    if write_cache:
        write_geometry_cache(series_directory, geometry)
    return geometry
