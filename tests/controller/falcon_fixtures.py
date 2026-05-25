"""Synthetic multi-slice CT DICOM fixtures for FALCON controller tests."""

from pathlib import Path

import pydicom
from pydicom.data import get_testdata_file

FALCON_MIN_SLICES = 11
DEFAULT_SYNTHETIC_SLICE_COUNT = 12
CT_SMALL_TEMPLATE = "CT_small.dcm"


def build_synthetic_ct_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_SYNTHETIC_SLICE_COUNT,
    series_uid: str = "1.2.826.0.1.3680043.8.498806137165147036080431708860",
) -> Path:
    """Build a directory of stacked CT DICOM slices suitable for FALCON preprocessing.

    Clones pydicom ``CT_small.dcm`` per slice with unique SOP Instance UIDs and
    incrementing ``ImagePositionPatient`` along Z.

    Args:
        output_dir: Directory to write ``slice_NNN.dcm`` files into (created if needed).
        num_slices: Number of slices to write (must be >= ``FALCON_MIN_SLICES``).
        series_uid: ``SeriesInstanceUID`` shared by all slices in the series.

    Returns:
        Path to the series directory (same as ``output_dir``).

    Raises:
        ValueError: If ``num_slices`` is below ``FALCON_MIN_SLICES``.
    """
    if num_slices < FALCON_MIN_SLICES:
        raise ValueError(f"num_slices must be at least {FALCON_MIN_SLICES}, got {num_slices}")

    series_dir = Path(output_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

    template_path = get_testdata_file(CT_SMALL_TEMPLATE)
    template = pydicom.dcmread(template_path)
    slice_thickness = float(getattr(template, "SliceThickness", 1.0))
    base_position = [float(v) for v in template.ImagePositionPatient]
    base_sop_uid = str(template.SOPInstanceUID)

    for index in range(num_slices):
        ds = pydicom.dcmread(template_path)
        ds.SeriesInstanceUID = series_uid
        ds.InstanceNumber = index + 1
        ds.SOPInstanceUID = f"{base_sop_uid}.{index + 1}"
        ds.ImagePositionPatient = [
            base_position[0],
            base_position[1],
            base_position[2] + index * slice_thickness,
        ]
        ds.SliceThickness = slice_thickness
        out_path = series_dir / f"slice_{index + 1:03d}.dcm"
        ds.save_as(out_path)

    return series_dir


def list_dcm_files(series_dir: Path) -> list[Path]:
    """Return sorted ``*.dcm`` paths under ``series_dir``."""
    return sorted(series_dir.glob("*.dcm"))
