"""Synthetic multi-slice CT DICOM fixtures for tseg and related controller tests."""

import math
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pydicom
from cv2 import FONT_HERSHEY_SIMPLEX, putText
from pydicom.data import get_testdata_file
from pydicom.uid import generate_uid

from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

SYNTHETIC_VOLUME_MIN_SLICES = 11
SYNTHETIC_PHANTOM_VERSION = 3
DEFAULT_SYNTHETIC_SLICE_COUNT = 12
DEFAULT_PHANTOM_SLICE_COUNT = 24
DEFAULT_PHANTOM_MATRIX = 256
DEFAULT_SLICE_THICKNESS_MM = 5.0
DEFAULT_PIXEL_SPACING_MM = (1.0, 1.0)

CT_SMALL_TEMPLATE = "CT_small.dcm"
SYNTHETIC_CT_SMALL_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_small"
SYNTHETIC_CT_HEAD_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_head"
SYNTHETIC_CT_CHEST_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_chest"
SYNTHETIC_CT_ABDOMEN_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_abdomen"

SYNTHETIC_CT_HEAD_SERIES_UID = "1.2.826.0.1.3680043.8.498.137165147036080431708901"
SYNTHETIC_CT_HEAD_STUDY_UID = "1.2.826.0.1.3680043.8.498.137165147036080431708902"
SYNTHETIC_CT_HEAD_SOP_PREFIX = "1.2.826.0.1.3680043.8.498.137165147036080431708903"

SYNTHETIC_CT_CHEST_SERIES_UID = "1.2.826.0.1.3680043.8.498.137165147036080431708911"
SYNTHETIC_CT_CHEST_STUDY_UID = "1.2.826.0.1.3680043.8.498.137165147036080431708912"
SYNTHETIC_CT_CHEST_SOP_PREFIX = "1.2.826.0.1.3680043.8.498.137165147036080431708913"

SYNTHETIC_CT_ABDOMEN_SERIES_UID = "1.2.826.0.1.3680043.8.498.137165147036080431708921"
SYNTHETIC_CT_ABDOMEN_STUDY_UID = "1.2.826.0.1.3680043.8.498.137165147036080431708922"
SYNTHETIC_CT_ABDOMEN_SOP_PREFIX = "1.2.826.0.1.3680043.8.498.137165147036080431708923"

_HU_AIR = -1000.0
_HU_LUNG = -800.0
_HU_CHEST_WALL_FAT = -90.0
_HU_SOFT_TISSUE = 40.0
_HU_UNENHANCED_BLOOD = 38.0
_HU_MEDIASTINUM = 42.0
_HU_BONE = 1000.0
_RESCALE_INTERCEPT = -1024.0


def build_synthetic_ct_small_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_SYNTHETIC_SLICE_COUNT,
    series_uid: str = "1.2.826.0.1.3680043.8.498806137165147036080431708860",
) -> Path:
    _validate_slice_count(num_slices)

    series_dir = Path(output_dir)
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=False)

    template_path = str(get_testdata_file(CT_SMALL_TEMPLATE))
    template = pydicom.dcmread(template_path)
    slice_thickness = float(getattr(template, "SliceThickness", 1.0))
    base_position = [float(value) for value in template.ImagePositionPatient]
    base_sop_uid = str(template.SOPInstanceUID)

    for index in range(num_slices):
        dataset = pydicom.dcmread(template_path)
        dataset.SeriesInstanceUID = series_uid
        dataset.InstanceNumber = index + 1
        dataset.SOPInstanceUID = f"{base_sop_uid}.{index + 1}"
        dataset.ImagePositionPatient = [
            base_position[0],
            base_position[1],
            base_position[2] + index * slice_thickness,
        ]
        dataset.SliceThickness = slice_thickness
        dataset.save_as(series_dir / f"slice_{index + 1:03d}.dcm")

    return series_dir


def build_synthetic_head_ct_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT,
    series_uid: str | None = None,
    study_uid: str | None = None,
    sop_instance_uid_prefix: str | None = None,
) -> Path:
    return _build_phantom_series(
        output_dir,
        slice_generator=_head_hu_slice,
        num_slices=num_slices,
        series_uid=series_uid,
        study_uid=study_uid,
        sop_instance_uid_prefix=sop_instance_uid_prefix,
        body_part_examined="HEAD",
        series_description="Synthetic head CT phantom",
    )


def build_synthetic_chest_ct_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT,
    series_uid: str | None = None,
    study_uid: str | None = None,
    sop_instance_uid_prefix: str | None = None,
) -> Path:
    return _build_phantom_series(
        output_dir,
        slice_generator=_chest_hu_slice,
        num_slices=num_slices,
        series_uid=series_uid,
        study_uid=study_uid,
        sop_instance_uid_prefix=sop_instance_uid_prefix,
        body_part_examined="CHEST",
        series_description="Synthetic chest CT phantom",
    )


def build_synthetic_wide_ct_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT,
    rows: int = DEFAULT_PHANTOM_MATRIX,
    cols: int = 2 * DEFAULT_PHANTOM_MATRIX,
    series_uid: str | None = None,
    study_uid: str | None = None,
    sop_instance_uid_prefix: str | None = None,
) -> Path:
    """Non-square chest phantom (default 256 rows x 512 columns).

    Square frames cannot detect width/height transposition in aspect-ratio maths, so
    Series View layout tests need a series whose two axes differ.
    """
    return _build_phantom_series(
        output_dir,
        slice_generator=_chest_hu_slice,
        num_slices=num_slices,
        series_uid=series_uid,
        study_uid=study_uid,
        sop_instance_uid_prefix=sop_instance_uid_prefix,
        body_part_examined="CHEST",
        series_description="Synthetic wide CT phantom",
        rows=rows,
        cols=cols,
    )


def build_synthetic_abdomen_ct_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT,
    series_uid: str | None = None,
    study_uid: str | None = None,
    sop_instance_uid_prefix: str | None = None,
) -> Path:
    return _build_phantom_series(
        output_dir,
        slice_generator=_abdomen_hu_slice,
        num_slices=num_slices,
        series_uid=series_uid,
        study_uid=study_uid,
        sop_instance_uid_prefix=sop_instance_uid_prefix,
        body_part_examined="ABDOMEN",
        series_description="Synthetic abdomen CT phantom",
    )


def build_synthetic_oriented_ct_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT,
    image_orientation: list[float],
    stack_delta: list[float],
    image_type: list[str] | None = None,
    series_description: str = "Synthetic chest CT phantom",
    body_part_examined: str = "CHEST",
    series_uid: str | None = None,
    study_uid: str | None = None,
    sop_instance_uid_prefix: str | None = None,
    require_min_volume_slices: bool = True,
) -> Path:
    """Build a synthetic chest phantom with custom IOP and stack direction."""
    if require_min_volume_slices:
        _validate_slice_count(num_slices)
    elif num_slices < 1:
        raise ValueError(f"num_slices must be at least 1, got {num_slices}")

    series_dir = Path(output_dir)
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=False)

    resolved_series_uid = series_uid or generate_uid()
    resolved_study_uid = study_uid or generate_uid()
    rows = cols = DEFAULT_PHANTOM_MATRIX
    pixel_spacing = DEFAULT_PIXEL_SPACING_MM
    slice_thickness = DEFAULT_SLICE_THICKNESS_MM
    origin = [-cols / 2 * pixel_spacing[1], -rows / 2 * pixel_spacing[0], 0.0]
    resolved_image_type = image_type or ["ORIGINAL", "PRIMARY", "AXIAL"]

    for index in range(num_slices):
        hu_slice = _chest_hu_slice(index, num_slices, rows, cols)
        sop_instance_uid = (
            f"{sop_instance_uid_prefix}.{index + 1}" if sop_instance_uid_prefix is not None else generate_uid()
        )
        dataset = _new_ct_dataset(
            hu_slice,
            instance_number=index + 1,
            series_uid=resolved_series_uid,
            study_uid=resolved_study_uid,
            sop_instance_uid=sop_instance_uid,
            image_position=[
                origin[0] + index * stack_delta[0],
                origin[1] + index * stack_delta[1],
                origin[2] + index * stack_delta[2],
            ],
            pixel_spacing=pixel_spacing,
            slice_thickness=slice_thickness,
            body_part_examined=body_part_examined,
            series_description=series_description,
            image_orientation=image_orientation,
            image_type=resolved_image_type,
        )
        dataset.save_as(series_dir / f"slice_{index + 1:03d}.dcm")

    return series_dir


def build_synthetic_sagittal_ct_series(output_dir: Path, *, num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT) -> Path:
    """Native sagittal stack: slice normal along patient X (LPS)."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        stack_delta=[DEFAULT_SLICE_THICKNESS_MM, 0.0, 0.0],
        image_type=["ORIGINAL", "PRIMARY", "SAGITTAL"],
        series_description="Synthetic sagittal chest CT phantom",
    )


def build_synthetic_coronal_ct_series(output_dir: Path, *, num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT) -> Path:
    """Native coronal stack: slice normal along patient Y (LPS)."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        stack_delta=[0.0, DEFAULT_SLICE_THICKNESS_MM, 0.0],
        image_type=["ORIGINAL", "PRIMARY", "CORONAL"],
        series_description="Synthetic coronal chest CT phantom",
    )


def build_synthetic_oblique_ct_series(output_dir: Path, *, num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT) -> Path:
    """Oblique acquisition: slice normal between axial and coronal."""
    step = DEFAULT_SLICE_THICKNESS_MM / math.sqrt(2)
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 0.70710678, 0.70710678],
        stack_delta=[0.0, -step, step],
        image_type=["ORIGINAL", "PRIMARY", "OBLIQUE"],
        series_description="Synthetic oblique chest CT phantom",
    )


def build_synthetic_scout_ct_series(output_dir: Path, *, num_slices: int = 5) -> Path:
    """Scout/localizer-style series: few slices with LOCALIZER ImageType."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 10.0],
        image_type=["ORIGINAL", "PRIMARY", "LOCALIZER"],
        series_description="SCOUT TOPOGRAM",
        require_min_volume_slices=False,
    )


def build_synthetic_haste_sag_series(output_dir: Path, *, num_slices: int = 26) -> Path:
    """Sagittal MR HASTE survey (localizer-style naming, many thick slices)."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[0.0, 1.0, 0.0, 0.0, 0.0, -1.0],
        stack_delta=[-9.6, 0.0, 0.0],
        image_type=["ORIGINAL", "PRIMARY", "OTHER"],
        series_description="LIVER-PELVIS/HASTE_SAG_POS",
        body_part_examined="ABDOMEN",
        require_min_volume_slices=False,
    )


def build_synthetic_breast_adc_mr_series(output_dir: Path, *, num_slices: int = 60) -> Path:
    """Derived secondary axial breast ADC map (parametric MR, not anatomical)."""
    series_dir = build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 2.5],
        image_type=["DERIVED", "SECONDARY", "AXIAL"],
        series_description="ADC = short int value x 0.2E-06 (units: 10E-03 mm^2/s)",
        body_part_examined="BREAST",
        require_min_volume_slices=False,
    )
    for path in series_dir.glob("*.dcm"):
        dataset = pydicom.dcmread(path)
        dataset.Modality = "MR"
        dataset.save_as(path)
    return series_dir


def build_synthetic_breast_mr_anatomical_series(output_dir: Path, *, num_slices: int = 60) -> Path:
    """Native breast MR volume (no breast class in total_mr ROI)."""
    series_dir = build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 2.5],
        image_type=["ORIGINAL", "PRIMARY", "AXIAL"],
        series_description="T2 AXIAL BREAST",
        body_part_examined="BREAST",
        require_min_volume_slices=False,
    )
    for path in series_dir.glob("*.dcm"):
        dataset = pydicom.dcmread(path)
        dataset.Modality = "MR"
        dataset.save_as(path)
    return series_dir


def build_synthetic_ct_perfusion_map_series(output_dir: Path, *, num_slices: int = 40) -> Path:
    """Derived CT perfusion map (CBF) — parametric, not anatomical."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 5.0],
        image_type=["DERIVED", "SECONDARY", "AXIAL"],
        series_description="CBF PERFUSION MAP",
        body_part_examined="BRAIN",
        require_min_volume_slices=False,
    )


def build_synthetic_survey_mr_series(output_dir: Path, *, num_slices: int = 40) -> Path:
    """Thick-slice MR survey classified as localizer."""
    series_dir = build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 8.0],
        image_type=["ORIGINAL", "PRIMARY", "AXIAL"],
        series_description="ABDOMEN SURVEY STIR",
        body_part_examined="ABDOMEN",
        require_min_volume_slices=False,
    )
    for path in series_dir.glob("*.dcm"):
        dataset = pydicom.dcmread(path)
        dataset.Modality = "MR"
        dataset.save_as(path)
    return series_dir


def build_synthetic_fused_pet_ct_series(output_dir: Path, *, num_slices: int = 40) -> Path:
    """PET/CT fusion series — metadata harmonize as Fused."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 3.0],
        image_type=["DERIVED", "SECONDARY", "AXIAL"],
        series_description="PET/CT FUSION",
        body_part_examined="CHEST",
        require_min_volume_slices=False,
    )


def build_synthetic_bolus_monitor_series(output_dir: Path, *, num_slices: int = 20) -> Path:
    """Bolus monitoring series — metadata harmonize as Monitoring."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 3.0],
        image_type=["ORIGINAL", "PRIMARY", "AXIAL"],
        series_description="BOLUS MONITOR",
        body_part_examined="CHEST",
        require_min_volume_slices=False,
    )


def build_synthetic_derived_coronal_mpr_series(
    output_dir: Path,
    *,
    num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT,
    source_series_uid: str = "1.2.826.0.1.3680043.8.498.137165147036080431709001",
) -> Path:
    """Derived coronal MPR-style series with referenced source UID."""
    series_dir = build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        stack_delta=[0.0, DEFAULT_SLICE_THICKNESS_MM, 0.0],
        image_type=["DERIVED", "SECONDARY", "REFORMATTED"],
        series_description="COR MPR REFORMAT",
    )
    ref_item = pydicom.Dataset()
    ref_item.SeriesInstanceUID = source_series_uid
    ref_sequence = pydicom.Sequence([ref_item])
    for path in sorted(series_dir.glob("*.dcm")):
        dataset = pydicom.dcmread(path)
        dataset.ReferencedSeriesSequence = ref_sequence
        dataset.save_as(path)
    return series_dir


def build_synthetic_derived_mip_series(output_dir: Path, *, num_slices: int = DEFAULT_PHANTOM_SLICE_COUNT) -> Path:
    """Derived MIP-style series unsuitable for TotalSegmentator."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=num_slices,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, DEFAULT_SLICE_THICKNESS_MM],
        image_type=["DERIVED", "SECONDARY", "PROJECTION"],
        series_description="3D MIP THICK SLAB",
    )


def build_synthetic_single_slice_ct_series(output_dir: Path) -> Path:
    """Single-slice diagnostic-style series."""
    return build_synthetic_oriented_ct_series(
        output_dir,
        num_slices=1,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, DEFAULT_SLICE_THICKNESS_MM],
        series_description="Single slice CT",
        require_min_volume_slices=False,
    )


def write_synthetic_phantom_assets() -> dict[str, Path]:
    return {
        SYNTHETIC_CT_HEAD_ASSET_DIR.name: build_synthetic_head_ct_series(
            SYNTHETIC_CT_HEAD_ASSET_DIR,
            series_uid=SYNTHETIC_CT_HEAD_SERIES_UID,
            study_uid=SYNTHETIC_CT_HEAD_STUDY_UID,
            sop_instance_uid_prefix=SYNTHETIC_CT_HEAD_SOP_PREFIX,
        ),
        SYNTHETIC_CT_CHEST_ASSET_DIR.name: build_synthetic_chest_ct_series(
            SYNTHETIC_CT_CHEST_ASSET_DIR,
            series_uid=SYNTHETIC_CT_CHEST_SERIES_UID,
            study_uid=SYNTHETIC_CT_CHEST_STUDY_UID,
            sop_instance_uid_prefix=SYNTHETIC_CT_CHEST_SOP_PREFIX,
        ),
        SYNTHETIC_CT_ABDOMEN_ASSET_DIR.name: build_synthetic_abdomen_ct_series(
            SYNTHETIC_CT_ABDOMEN_ASSET_DIR,
            series_uid=SYNTHETIC_CT_ABDOMEN_SERIES_UID,
            study_uid=SYNTHETIC_CT_ABDOMEN_STUDY_UID,
            sop_instance_uid_prefix=SYNTHETIC_CT_ABDOMEN_SOP_PREFIX,
        ),
    }


def list_dcm_files(series_dir: Path) -> list[Path]:
    return sorted(series_dir.glob("*.dcm"))


def _validate_slice_count(num_slices: int) -> None:
    if num_slices < SYNTHETIC_VOLUME_MIN_SLICES:
        raise ValueError(f"num_slices must be at least {SYNTHETIC_VOLUME_MIN_SLICES}, got {num_slices}")


def _build_phantom_series(
    output_dir: Path,
    *,
    slice_generator: Callable[[int, int, int, int], np.ndarray],
    num_slices: int,
    series_uid: str | None,
    study_uid: str | None = None,
    sop_instance_uid_prefix: str | None = None,
    body_part_examined: str,
    series_description: str,
    rows: int = DEFAULT_PHANTOM_MATRIX,
    cols: int = DEFAULT_PHANTOM_MATRIX,
) -> Path:
    _validate_slice_count(num_slices)

    series_dir = Path(output_dir)
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=False)

    resolved_series_uid = series_uid or generate_uid()
    resolved_study_uid = study_uid or generate_uid()

    pixel_spacing = DEFAULT_PIXEL_SPACING_MM
    slice_thickness = DEFAULT_SLICE_THICKNESS_MM
    origin = [-cols / 2 * pixel_spacing[1], -rows / 2 * pixel_spacing[0], 0.0]

    for index in range(num_slices):
        hu_slice = slice_generator(index, num_slices, rows, cols)
        sop_instance_uid = (
            f"{sop_instance_uid_prefix}.{index + 1}" if sop_instance_uid_prefix is not None else generate_uid()
        )
        dataset = _new_ct_dataset(
            hu_slice,
            instance_number=index + 1,
            series_uid=resolved_series_uid,
            study_uid=resolved_study_uid,
            sop_instance_uid=sop_instance_uid,
            image_position=[
                origin[0],
                origin[1],
                origin[2] + index * slice_thickness,
            ],
            pixel_spacing=pixel_spacing,
            slice_thickness=slice_thickness,
            body_part_examined=body_part_examined,
            series_description=series_description,
        )
        dataset.save_as(series_dir / f"slice_{index + 1:03d}.dcm")

    return series_dir


def _new_ct_dataset(
    hu_slice: np.ndarray,
    *,
    instance_number: int,
    series_uid: str,
    study_uid: str,
    sop_instance_uid: str,
    image_position: list[float],
    pixel_spacing: tuple[float, float],
    slice_thickness: float,
    body_part_examined: str,
    series_description: str,
    image_orientation: list[float] | None = None,
    image_type: list[str] | None = None,
) -> pydicom.Dataset:
    dataset = pydicom.dcmread(str(get_testdata_file(CT_SMALL_TEMPLATE)))
    rows, cols = hu_slice.shape
    stored_pixels = _hu_to_stored_pixels(hu_slice)

    dataset.SeriesInstanceUID = series_uid
    dataset.StudyInstanceUID = study_uid
    dataset.SOPInstanceUID = sop_instance_uid
    dataset.InstanceNumber = instance_number
    dataset.PatientName = "Synthetic^Phantom"
    dataset.PatientID = "SYN001"
    dataset.BodyPartExamined = body_part_examined
    dataset.SeriesDescription = series_description
    dataset.ImageType = image_type or ["ORIGINAL", "PRIMARY", "AXIAL"]
    dataset.Rows = rows
    dataset.Columns = cols
    dataset.PixelSpacing = [pixel_spacing[0], pixel_spacing[1]]
    dataset.SliceThickness = slice_thickness
    dataset.ImageOrientationPatient = image_orientation or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    dataset.ImagePositionPatient = image_position
    dataset.RescaleSlope = 1
    dataset.RescaleIntercept = _RESCALE_INTERCEPT
    dataset.PixelData = stored_pixels.tobytes()
    return dataset


def _hu_to_stored_pixels(hu_slice: np.ndarray) -> np.ndarray:
    stored = hu_slice - _RESCALE_INTERCEPT
    return np.clip(stored, -32768, 32767).astype(np.int16)


def _coordinate_grids(rows: int, cols: int):
    y = np.arange(rows, dtype=np.float32) - rows / 2
    x = np.arange(cols, dtype=np.float32) - cols / 2
    return np.meshgrid(x, y, indexing="xy")


def _head_hu_slice(index: int, num_slices: int, rows: int, cols: int) -> np.ndarray:
    xx, yy = _coordinate_grids(rows, cols)
    zz = (index - (num_slices - 1) / 2) * DEFAULT_SLICE_THICKNESS_MM
    radius = np.sqrt((xx / 72.0) ** 2 + (yy / 72.0) ** 2 + (zz / 50.0) ** 2)

    hu = np.full((rows, cols), _HU_AIR, dtype=np.float32)
    brain = radius <= 0.68
    skull = (radius > 0.68) & (radius <= 0.98)
    hu[brain] = 36.0
    hu[skull] = 750.0

    # Midline nasal cavity (avoid bilateral air pockets that mimic chest lungs).
    if num_slices // 3 <= index <= (2 * num_slices) // 3:
        nasal = (xx / 7.0) ** 2 + ((yy - 38.0) / 10.0) ** 2 <= 1.0
        hu[nasal & brain] = _HU_AIR

    hu += np.random.default_rng(index + 1).normal(0.0, 4.0, size=(rows, cols))
    hu[radius > 1.05] = _HU_AIR
    hu[skull] = np.maximum(hu[skull], 650.0)
    return hu.astype(np.float32)


def _chest_hu_slice(index: int, num_slices: int, rows: int, cols: int) -> np.ndarray:
    xx, yy = _coordinate_grids(rows, cols)
    zz = (index - (num_slices - 1) / 2) * DEFAULT_SLICE_THICKNESS_MM
    distance = np.sqrt(xx**2 + yy**2)

    hu = np.full((rows, cols), _HU_AIR, dtype=np.float32)

    chest_wall = distance <= 95
    hu[chest_wall] = _HU_SOFT_TISSUE

    chest_fat = (distance > 82) & (distance <= 95)
    hu[chest_fat] = _HU_CHEST_WALL_FAT

    lung_slice_start = num_slices // 2 - 2
    lung_slice_end = num_slices - 4
    if lung_slice_start <= index <= lung_slice_end:
        lung_left = ((xx + 35.0) / 45.0) ** 2 + (yy / 55.0) ** 2 + (zz / 90.0) ** 2 <= 1.0
        lung_right = ((xx - 35.0) / 45.0) ** 2 + (yy / 55.0) ** 2 + (zz / 90.0) ** 2 <= 1.0
        hu[lung_left | lung_right] = _HU_LUNG

    mediastinum = (xx / 22.0) ** 2 + (yy / 28.0) ** 2 <= 1.0
    hu[mediastinum] = _HU_MEDIASTINUM

    aorta = (xx / 6.0) ** 2 + ((yy + 6.0) / 8.0) ** 2 <= 1.0
    hu[aorta] = _HU_UNENHANCED_BLOOD

    ribs = (distance > 88) & (distance < 98) & ((np.abs(xx) + np.abs(yy)) % 28 < 4)
    hu[ribs] = 650.0

    non_bone = hu < 300.0
    hu[non_bone] = np.clip(hu[non_bone], _HU_LUNG, 55.0)
    hu += np.random.default_rng(index + 101).normal(0.0, 6.0, size=(rows, cols))
    hu[non_bone] = np.clip(hu[non_bone], _HU_LUNG, 55.0)
    return hu.astype(np.float32)


def _abdomen_hu_slice(index: int, num_slices: int, rows: int, cols: int) -> np.ndarray:
    xx, yy = _coordinate_grids(rows, cols)
    zz = (index - (num_slices - 1) / 2) * DEFAULT_SLICE_THICKNESS_MM

    hu = np.full((rows, cols), _HU_SOFT_TISSUE, dtype=np.float32)
    hu[np.sqrt(xx**2 + yy**2) > 105] = _HU_AIR

    liver = ((xx + 18.0) / 42.0) ** 2 + (yy / 36.0) ** 2 + (zz / 70.0) ** 2 <= 1.0
    hu[liver] = 55.0

    spleen = ((xx - 40.0) / 18.0) ** 2 + ((yy + 8.0) / 20.0) ** 2 <= 1.0
    hu[spleen] = 48.0

    kidney_left = ((xx + 28.0) / 12.0) ** 2 + ((yy + 18.0) / 18.0) ** 2 <= 1.0
    kidney_right = ((xx - 28.0) / 12.0) ** 2 + ((yy + 18.0) / 18.0) ** 2 <= 1.0
    hu[kidney_left | kidney_right] = 35.0

    spine = (xx / 10.0) ** 2 + ((yy + 42.0) / 12.0) ** 2 <= 1.0
    hu[spine] = _HU_BONE

    bowel = ((xx / 55.0) ** 2 + (yy / 40.0) ** 2 + (zz / 45.0) ** 2 <= 1.0) & (hu == _HU_SOFT_TISSUE)
    hu[bowel & (np.abs(xx + yy + index * 7) % 31 < 5)] = _HU_LUNG

    hu += np.random.default_rng(index + 201).normal(0.0, 10.0, size=(rows, cols))
    return hu.astype(np.float32)


DEFAULT_BURNED_IN_PHI_LINES: tuple[str, ...] = ("SMITH^JOHN", "01-Jan-2024")
_BURNED_IN_PHI_HU = 3071.0
_BURNED_IN_PHI_BACKGROUND_HU = -200.0


def burn_phi_overlay_on_hu_slice(
    hu_slice: np.ndarray,
    lines: Sequence[str],
    *,
    origin: tuple[int, int] = (24, 40),
    line_spacing_px: int = 32,
) -> np.ndarray:
    """Simulate bright burnt-in patient overlay text on a CT HU slice."""
    mask = np.zeros(hu_slice.shape, dtype=np.uint8)
    x, y = origin
    banner_bottom = y + len(lines) * line_spacing_px + 12
    banner_right = min(hu_slice.shape[1] - 1, x + 260)
    result = hu_slice.copy()
    result[20:banner_bottom, 20:banner_right] = _BURNED_IN_PHI_BACKGROUND_HU
    for index, line in enumerate(lines):
        putText(
            mask,
            line,
            (x, y + index * line_spacing_px),
            FONT_HERSHEY_SIMPLEX,
            0.9,
            255,
            2,
        )
    result[mask > 0] = _BURNED_IN_PHI_HU
    return result


def apply_burned_in_phi_to_dicom(path: Path, lines: Sequence[str] = DEFAULT_BURNED_IN_PHI_LINES) -> None:
    """Burn sample PHI overlay text into an on-disk synthetic CT slice."""
    dataset = pydicom.dcmread(path)
    hu_slice = dataset.pixel_array.astype(np.float32)
    burned = burn_phi_overlay_on_hu_slice(hu_slice, lines)
    dataset.PixelData = _hu_to_stored_pixels(burned).tobytes()
    dataset.save_as(path)


def build_synthetic_ct_series_with_burned_in_phi(
    output_dir: Path,
    *,
    phi_lines: Sequence[str] = DEFAULT_BURNED_IN_PHI_LINES,
    burn_slice_index: int = 0,
    num_slices: int = SYNTHETIC_VOLUME_MIN_SLICES,
) -> Path:
    """Build a synthetic chest CT series with burnt-in PHI on one slice."""
    series_dir = build_synthetic_chest_ct_series(output_dir, num_slices=num_slices)
    slice_paths = list_dcm_files(series_dir)
    if not 0 <= burn_slice_index < len(slice_paths):
        raise IndexError(f"burn_slice_index {burn_slice_index} out of range for {len(slice_paths)} slices")
    apply_burned_in_phi_to_dicom(slice_paths[burn_slice_index], phi_lines)
    return series_dir


if __name__ == "__main__":
    print(f"Generating synthetic CT DICOM assets in: {CONTROLLER_TEST_DCM_FILES_DIR}")

    generated_assets = write_synthetic_phantom_assets()

    print("\nGeneration Complete! Asset Directories created/updated:")
    for key, path in generated_assets.items():
        print(f" - {key}: {len(list_dcm_files(path))} slices")
