#!/usr/bin/env python3
"""
Run Series View face-blur + save pipeline and verify DICOM integrity.

Mirrors the controller path used when the user clicks **Save Pixel Changes** in
Series View (``preview_face_blur`` → ``apply_face_blur_preview_to_series_frames``
→ ``save_series_frames``), writing to a separate output directory instead of
overwriting the source series.

Default output: ``<series_directory>/1_blurred_face``

Usage::

    uv sync --extra tseg --group dev
    uv run python -m prototyping.ffr.face.save_integrity /path/to/ct_head_series
    uv run python -m prototyping.ffr.face.save_integrity /path/to/series --check-only
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np
import pydicom
from pydicom import Dataset, dcmread
from pydicom.datadict import keyword_for_tag
from pydicom.tag import Tag

from anonymizer.controller.blur_face import (
    DEFAULT_FACE_BLUR_SIGMA_MM,
    SeriesVolumeContext,
    align_mask_to_volume,
    apply_face_blur_preview_to_series_frames,
    compute_qa_stats,
    hu_stack_from_series_frames,
    load_hu_stack,
    mask_array_from_volume,
    preview_face_blur,
    read_reference_volume,
    resolve_face_mask_path,
)
from anonymizer.controller.series_io import (
    load_series_frames,
    ordered_series_dcm_paths,
    save_series_frames,
)
from anonymizer.controller.tseg.dicom_geometry import (
    load_geometry_cache,
    project_ipp_onto_normal,
    slice_normal_from_iop,
    stackable_dicom_paths,
)

logger = logging.getLogger("prototyping.ffr.face.save_integrity")

DEFAULT_OUTPUT_DIRNAME = "1_blurred_face"

# Tags that save_series_frames may change (pixel payload and transfer syntax only).
EXPECTED_PIXEL_SAVE_CHANGES: frozenset[str] = frozenset(
    {
        "PixelData",
        "TransferSyntaxUID",
    }
)

# Must match between source and output (paired by SOPInstanceUID).
PRESERVE_TAGS: tuple[str, ...] = (
    "SOPInstanceUID",
    "SeriesInstanceUID",
    "StudyInstanceUID",
    "FrameOfReferenceUID",
    "PatientID",
    "PatientName",
    "AccessionNumber",
    "StudyID",
    "Modality",
    "InstanceNumber",
    "ImagePositionPatient",
    "ImageOrientationPatient",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
    "Rows",
    "Columns",
    "PhotometricInterpretation",
    "SamplesPerPixel",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "RescaleSlope",
    "RescaleIntercept",
    "WindowCenter",
    "WindowWidth",
    "SeriesDescription",
    "SeriesNumber",
    "StudyDate",
    "StudyTime",
    "AcquisitionDate",
    "AcquisitionTime",
    "ConvolutionKernel",
    "KVP",
    "ExposureTime",
    "XRayTubeCurrent",
    "ProtocolName",
    "BodyPartExamined",
)


class Severity(StrEnum):
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


@dataclass(frozen=True)
class IntegrityIssue:
    severity: Severity
    category: str
    message: str
    slice_index: int | None = None
    tag: str | None = None


@dataclass
class IntegrityReport:
    source_directory: Path
    output_directory: Path
    issues: list[IntegrityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == Severity.ERROR for issue in self.issues)

    def add(self, issue: IntegrityIssue) -> None:
        self.issues.append(issue)

    def summary_lines(self) -> list[str]:
        counts = {severity: 0 for severity in Severity}
        for issue in self.issues:
            counts[issue.severity] += 1
        return [
            f"Integrity: {'PASS' if self.ok else 'FAIL'} "
            f"(errors={counts[Severity.ERROR]}, warnings={counts[Severity.WARN]}, info={counts[Severity.INFO]})",
            f"  source={self.source_directory}",
            f"  output={self.output_directory}",
        ]


def default_output_directory(series_directory: Path) -> Path:
    return Path(series_directory).resolve() / DEFAULT_OUTPUT_DIRNAME


def _build_viewer_frames(series_frames: np.ndarray) -> np.ndarray:
    """Same layout as ``SeriesView._build_viewer_frames`` (3 projections + slices)."""
    slice_count = series_frames.shape[0]
    frames = np.empty((slice_count + 3,) + series_frames.shape[1:], dtype=series_frames.dtype)
    np.copyto(frames[3:], series_frames)

    proj_min = np.copy(frames[3])
    proj_max = np.copy(frames[3])
    proj_sum = frames[3].astype(np.float32, copy=True)
    for slice_index in range(4, frames.shape[0]):
        slice_frame = frames[slice_index]
        np.minimum(proj_min, slice_frame, out=proj_min)
        np.maximum(proj_max, slice_frame, out=proj_max)
        proj_sum += slice_frame

    frames[0] = proj_min
    frames[2] = proj_max
    frames[1] = (proj_sum / slice_count).astype(frames.dtype, copy=False)
    return frames


def _prepare_output_slices(source_directory: Path, output_directory: Path, slice_paths: Sequence[Path]) -> None:
    output_directory = Path(output_directory).resolve()
    if output_directory.exists():
        for path in output_directory.iterdir():
            if path.is_file() and path.suffix.lower() in {".dcm", ".dicom"}:
                path.unlink()
    else:
        output_directory.mkdir(parents=True, exist_ok=True)

    source_directory = Path(source_directory).resolve()
    for slice_path in slice_paths:
        source_file = slice_path if slice_path.is_file() else source_directory / slice_path.name
        destination = output_directory / source_file.name
        shutil.copy2(source_file, destination)


def run_series_view_face_blur_save(
    series_directory: Path,
    output_directory: Path,
    *,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    run_segmentation_if_missing: bool = True,
    force_segmentation: bool = False,
) -> tuple[bool, str | None]:
    """
    Execute the Series View blur + save pipeline into ``output_directory``.

    Returns ``(save_ok, error_message)``.
    """
    series_directory = Path(series_directory).resolve()
    output_directory = Path(output_directory).resolve()

    loaded = load_series_frames(series_directory)

    reference_ds, series_frames, slice_paths = loaded.metadata, loaded.frames, loaded.slice_paths
    single_frame = series_frames.shape[0] == 1
    viewer_frames = series_frames if single_frame else _build_viewer_frames(series_frames)

    geometry = load_geometry_cache(series_directory)
    volume_context = SeriesVolumeContext(
        reference_ds=reference_ds,
        slice_frames=series_frames,
        slice_paths=slice_paths,
        slice_spacing_mm=geometry.slice_spacing_mm if geometry is not None else None,
    )

    preview = preview_face_blur(
        series_directory,
        sigma_mm=sigma_mm,
        run_segmentation_if_missing=run_segmentation_if_missing,
        force_segmentation=force_segmentation,
        volume_context=volume_context,
    )
    if preview.error is not None:
        return False, preview.error
    if preview.qa_stats is not None and not preview.qa_stats.outside_clean:
        logger.warning(
            "Blur QA: %d voxels outside face mask changed (max |Δ|=%.3f HU)",
            preview.qa_stats.n_violating_voxels,
            preview.qa_stats.max_abs_diff_outside,
        )

    merged_frames = apply_face_blur_preview_to_series_frames(
        viewer_frames,
        preview,
        single_frame=single_frame,
        reference_ds=reference_ds,
        frame_dtype=series_frames.dtype,
    )
    slices_to_save = merged_frames if single_frame else merged_frames[3:]

    _prepare_output_slices(series_directory, output_directory, slice_paths)
    save_ok = save_series_frames(output_directory, slices_to_save, reference_ds)
    if not save_ok:
        return False, "save_series_frames returned False"
    return True, None


def _read_header(path: Path) -> Dataset:
    return dcmread(str(path), stop_before_pixels=True, force=True)


def _tag_value(dataset: Dataset, tag_name: str) -> object | None:
    if tag_name not in dataset:
        return None
    value = dataset.get(tag_name)
    if hasattr(value, "original_string"):
        return value.original_string.decode(errors="replace") if isinstance(value.original_string, bytes) else str(value)
    if isinstance(value, pydicom.multival.MultiValue):
        return tuple(value)
    if isinstance(value, pydicom.sequence.Sequence):
        return len(value)
    return value


def _values_equal(left: object | None, right: object | None, *, tag_name: str) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    if tag_name in {"WindowCenter", "WindowWidth"}:
        try:
            return np.allclose(np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64), rtol=0, atol=1e-3)
        except (TypeError, ValueError):
            return str(left) == str(right)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        if len(left) != len(right):
            return False
        for a, b in zip(left, right, strict=True):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if not np.isclose(float(a), float(b), rtol=0, atol=1e-4):
                    return False
            elif a != b:
                return False
        return True
    return left == right


def _stack_sop_uids(paths: Sequence[Path]) -> list[str]:
    return [str(_read_header(path).SOPInstanceUID) for path in paths]


def _save_iteration_paths(series_directory: Path) -> list[Path]:
    """Paths in the order ``save_series_frames`` iterates (stack order)."""
    return ordered_series_dcm_paths(series_directory)


def check_save_order_hazard(series_directory: Path, report: IntegrityReport) -> None:
    """Detect stack order vs save order mismatch (common cause of scrambled slices)."""
    stack_paths = stackable_dicom_paths(series_directory)
    save_paths = _save_iteration_paths(series_directory)
    stack_sops = _stack_sop_uids(stack_paths)
    save_sops = _stack_sop_uids(save_paths)

    if stack_sops == save_sops:
        report.add(
            IntegrityIssue(
                Severity.INFO,
                "save_order",
                "Stack order matches save_series_frames iteration order.",
            )
        )
        return

    first_mismatch: int | None = None
    for index, (stack_sop, save_sop) in enumerate(zip(stack_sops, save_sops, strict=False)):
        if stack_sop != save_sop:
            first_mismatch = index
            break

    report.add(
        IntegrityIssue(
            Severity.ERROR,
            "save_order",
            "save_series_frames iteration order differs from stackable_dicom_paths() "
            f"stack order (first mismatch at index {first_mismatch}). "
            "Processed pixels may be written to the wrong slice files.",
        )
    )


def check_stack_order(source_paths: Sequence[Path], output_paths: Sequence[Path], report: IntegrityReport) -> None:
    source_sops = _stack_sop_uids(source_paths)
    output_sops = _stack_sop_uids(output_paths)
    if source_sops == output_sops:
        report.add(
            IntegrityIssue(
                Severity.INFO,
                "stack_order",
                f"Stack order identical ({len(source_sops)} slices, same SOPInstanceUID sequence).",
            )
        )
        return

    report.add(
        IntegrityIssue(
            Severity.ERROR,
            "stack_order",
            "Output stack SOPInstanceUID sequence differs from source.",
        )
    )

    for index, (source_sop, output_sop) in enumerate(zip(source_sops, output_sops, strict=False)):
        if source_sop != output_sop:
            report.add(
                IntegrityIssue(
                    Severity.ERROR,
                    "stack_order",
                    f"Index {index}: source SOP={source_sop} output SOP={output_sop}",
                    slice_index=index,
                )
            )


def check_ipp_monotonic(paths: Sequence[Path], report: IntegrityReport, *, label: str) -> None:
    headers = [_read_header(path) for path in paths]
    if not headers:
        return
    try:
        normal = slice_normal_from_iop(headers[0].ImageOrientationPatient)
        positions = [project_ipp_onto_normal(header.ImagePositionPatient, normal) for header in headers]
    except Exception as exc:
        report.add(
            IntegrityIssue(
                Severity.WARN,
                "geometry",
                f"{label}: could not verify IPP monotonicity: {exc}",
            )
        )
        return

    if positions == sorted(positions) or positions == sorted(positions, reverse=True):
        report.add(
            IntegrityIssue(
                Severity.INFO,
                "geometry",
                f"{label}: ImagePositionPatient monotonic along slice normal.",
            )
        )
    else:
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "geometry",
                f"{label}: ImagePositionPatient order is not monotonic along slice normal.",
            )
        )


def check_metadata_preserved(
    source_paths: Sequence[Path],
    output_paths: Sequence[Path],
    report: IntegrityReport,
) -> None:
    source_by_sop = {str(_read_header(path).SOPInstanceUID): path for path in source_paths}
    output_by_sop = {str(_read_header(path).SOPInstanceUID): path for path in output_paths}

    missing = set(source_by_sop) - set(output_by_sop)
    extra = set(output_by_sop) - set(source_by_sop)
    if missing:
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "metadata",
                f"Output missing {len(missing)} source SOPInstanceUID(s).",
            )
        )
    if extra:
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "metadata",
                f"Output has {len(extra)} unexpected SOPInstanceUID(s).",
            )
        )

    for index, source_path in enumerate(source_paths):
        source_header = _read_header(source_path)
        sop = str(source_header.SOPInstanceUID)
        output_path = output_by_sop.get(sop)
        if output_path is None:
            continue
        output_header = _read_header(output_path)

        for tag_name in PRESERVE_TAGS:
            source_value = _tag_value(source_header, tag_name)
            output_value = _tag_value(output_header, tag_name)
            if not _values_equal(source_value, output_value, tag_name=tag_name):
                report.add(
                    IntegrityIssue(
                        Severity.ERROR,
                        "metadata",
                        f"SOP {sop}: {tag_name} changed ({source_value!r} → {output_value!r})",
                        slice_index=index,
                        tag=tag_name,
                    )
                )

        for tag_name in EXPECTED_PIXEL_SAVE_CHANGES:
            source_value = _tag_value(source_header, tag_name)
            output_value = _tag_value(output_header, tag_name)
            if _values_equal(source_value, output_value, tag_name=tag_name):
                continue
            if tag_name == "PixelData":
                continue
            report.add(
                IntegrityIssue(
                    Severity.WARN,
                    "metadata",
                    f"SOP {sop}: {tag_name} changed ({source_value!r} → {output_value!r})",
                    slice_index=index,
                    tag=tag_name,
                )
            )


def check_unexpected_tag_changes(
    source_paths: Sequence[Path],
    output_paths: Sequence[Path],
    report: IntegrityReport,
) -> None:
    """Flag any non-pixel element changes outside the expected save path set."""
    skip_tags = {Tag(0x7FE0, 0x0010)}  # PixelData
    allowed = EXPECTED_PIXEL_SAVE_CHANGES | {"ImplementationClassUID", "ImplementationVersionName"}

    source_by_sop = {str(_read_header(path).SOPInstanceUID): _read_header(path) for path in source_paths}
    output_by_sop = {str(_read_header(path).SOPInstanceUID): _read_header(path) for path in output_paths}

    for sop, source_ds in source_by_sop.items():
        output_ds = output_by_sop.get(sop)
        if output_ds is None:
            continue
        source_tags = {elem.tag for elem in source_ds.iterall() if elem.tag not in skip_tags}
        output_tags = {elem.tag for elem in output_ds.iterall() if elem.tag not in skip_tags}
        for tag in sorted(source_tags | output_tags):
            try:
                keyword = keyword_for_tag(tag)
            except KeyError:
                keyword = str(tag)
            if keyword in allowed:
                continue
            source_value = _tag_value(source_ds, keyword) if keyword in source_ds else None
            output_value = _tag_value(output_ds, keyword) if keyword in output_ds else None
            if not _values_equal(source_value, output_value, tag_name=keyword):
                report.add(
                    IntegrityIssue(
                        Severity.ERROR,
                        "metadata_full",
                        f"SOP {sop}: unexpected change in {keyword} ({source_value!r} → {output_value!r})",
                        tag=keyword,
                    )
                )


def load_saved_output_hu_stack(output_paths: Sequence[Path]) -> np.ndarray:
    """Reload HU from saved slices using each output file's DICOM rescale tags."""
    return load_hu_stack(tuple(output_paths))


def load_source_hu_for_blur_pipeline(source_directory: Path, source_paths: Sequence[Path]) -> np.ndarray:
    """HU stack in stack order using the same loader as face blur / Series View."""
    loaded = load_series_frames(source_directory)
    _reference_ds, frames, loaded_paths = loaded.metadata, loaded.frames, loaded.slice_paths
    if tuple(loaded_paths) != tuple(source_paths):
        raise ValueError("Source stack paths do not match load_series_frames order")
    return hu_stack_from_series_frames(frames)


def check_outside_mask_pixels(
    source_paths: Sequence[Path],
    output_paths: Sequence[Path],
    series_directory: Path,
    report: IntegrityReport,
) -> None:
    try:
        mask_path = resolve_face_mask_path(series_directory, run_if_missing=False)
        volume_img, _ = read_reference_volume(series_directory)
        mask = mask_array_from_volume(align_mask_to_volume(mask_path, volume_img))
    except Exception as exc:
        report.add(
            IntegrityIssue(
                Severity.WARN,
                "pixels",
                f"Skipping outside-mask pixel check (no mask): {exc}",
            )
        )
        return

    try:
        hu_before = load_source_hu_for_blur_pipeline(series_directory, source_paths)
    except Exception as exc:
        report.add(
            IntegrityIssue(
                Severity.WARN,
                "pixels",
                f"Could not load source HU via blur pipeline: {exc}",
            )
        )
        return

    hu_after = load_saved_output_hu_stack(output_paths)
    stats = compute_qa_stats(hu_before, hu_after, mask)
    if stats.outside_clean:
        report.add(
            IntegrityIssue(
                Severity.INFO,
                "pixels",
                f"Outside face mask unchanged in HU space ({stats.n_outside_voxels} voxels checked).",
            )
        )
    else:
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "pixels",
                f"Outside face mask HU changed: {stats.n_violating_voxels} voxels, "
                f"max |Δ|={stats.max_abs_diff_outside:.3f} HU",
            )
        )

    check_rescale_tag_consistency(source_paths, output_paths, report)


def check_rescale_tag_consistency(
    source_paths: Sequence[Path],
    output_paths: Sequence[Path],
    report: IntegrityReport,
) -> None:
    """Ensure rescale tags were preserved (required for correct HU in all viewers)."""
    mismatches = 0
    for index, (source_path, output_path) in enumerate(zip(source_paths, output_paths, strict=True)):
        source_header = _read_header(source_path)
        output_header = _read_header(output_path)
        source_slope = float(getattr(source_header, "RescaleSlope", 1) or 1)
        source_intercept = float(getattr(source_header, "RescaleIntercept", 0) or 0)
        output_slope = float(getattr(output_header, "RescaleSlope", 1) or 1)
        output_intercept = float(getattr(output_header, "RescaleIntercept", 0) or 0)
        if np.isclose(source_slope, output_slope) and np.isclose(source_intercept, output_intercept):
            continue
        mismatches += 1
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "rescale",
                f"Slice {index}: RescaleSlope/Intercept not preserved "
                f"({source_slope}/{source_intercept} → {output_slope}/{output_intercept})",
                slice_index=index,
            )
        )
    if mismatches == 0:
        report.add(
            IntegrityIssue(
                Severity.INFO,
                "rescale",
                "RescaleSlope/RescaleIntercept preserved on all slices.",
            )
        )


def verify_series_integrity(
    source_directory: Path,
    output_directory: Path,
    *,
    check_pixels: bool = True,
) -> IntegrityReport:
    source_directory = Path(source_directory).resolve()
    output_directory = Path(output_directory).resolve()
    report = IntegrityReport(source_directory=source_directory, output_directory=output_directory)

    if not output_directory.is_dir():
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "io",
                f"Output directory does not exist: {output_directory}",
            )
        )
        return report

    try:
        source_stack = stackable_dicom_paths(source_directory)
    except ValueError as exc:
        report.add(IntegrityIssue(Severity.ERROR, "io", f"Source stack: {exc}"))
        return report

    try:
        output_stack = stackable_dicom_paths(output_directory)
    except ValueError as exc:
        report.add(IntegrityIssue(Severity.ERROR, "io", f"Output stack: {exc}"))
        return report

    if len(source_stack) != len(output_stack):
        report.add(
            IntegrityIssue(
                Severity.ERROR,
                "io",
                f"Slice count mismatch: source={len(source_stack)} output={len(output_stack)}",
            )
        )

    check_save_order_hazard(source_directory, report)
    check_stack_order(source_stack, output_stack, report)
    check_ipp_monotonic(source_stack, report, label="source")
    check_ipp_monotonic(output_stack, report, label="output")
    check_metadata_preserved(source_stack, output_stack, report)
    check_unexpected_tag_changes(source_stack, output_stack, report)
    if check_pixels:
        check_outside_mask_pixels(source_stack, output_stack, source_directory, report)

    return report


def print_report(report: IntegrityReport) -> None:
    for line in report.summary_lines():
        print(line)
    for issue in report.issues:
        prefix = issue.severity.value
        location = ""
        if issue.slice_index is not None:
            location += f" slice={issue.slice_index}"
        if issue.tag:
            location += f" tag={issue.tag}"
        print(f"  [{prefix}] {issue.category}{location}: {issue.message}")


def _configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Series View face blur save pipeline with DICOM integrity checks.",
    )
    parser.add_argument(
        "series_directory",
        type=Path,
        help="Path to source CT series directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output directory (default: <series>/{DEFAULT_OUTPUT_DIRNAME})",
    )
    parser.add_argument(
        "--sigma-mm",
        type=float,
        default=DEFAULT_FACE_BLUR_SIGMA_MM,
        help=f"Gaussian blur sigma in mm (default: {DEFAULT_FACE_BLUR_SIGMA_MM})",
    )
    parser.add_argument(
        "--force-segmentation",
        action="store_true",
        help="Re-run TotalSegmentator face segmentation",
    )
    parser.add_argument(
        "--no-segmentation",
        action="store_true",
        help="Do not run segmentation if mask is missing (fail instead)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Skip blur/save; only run integrity checks on existing output",
    )
    parser.add_argument(
        "--skip-pixel-check",
        action="store_true",
        help="Skip outside-mask HU comparison (metadata/order checks still run)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    series_directory = Path(args.series_directory).resolve()
    if not series_directory.is_dir():
        logger.error("Not a directory: %s", series_directory)
        return 1

    output_directory = Path(args.output).resolve() if args.output else default_output_directory(series_directory)

    if not args.check_only:
        logger.info("Processing %s → %s", series_directory, output_directory)
        save_ok, error = run_series_view_face_blur_save(
            series_directory,
            output_directory,
            sigma_mm=args.sigma_mm,
            run_segmentation_if_missing=not args.no_segmentation,
            force_segmentation=args.force_segmentation,
        )
        if not save_ok:
            logger.error("Face blur save failed: %s", error)
            return 1
        logger.info("Save completed: %s", output_directory)
    elif not output_directory.is_dir():
        logger.error("Check-only mode requires existing output: %s", output_directory)
        return 1

    report = verify_series_integrity(
        series_directory,
        output_directory,
        check_pixels=not args.skip_pixel_check,
    )
    print_report(report)
    return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())
