"""Dicom tree helpers for the anonymizer.

Public API
----------
DICOM_FILE_SUFFIX
    Dicom file suffix (default '.dcm').

is_hidden_name(name: str) -> bool
    True for dot-prefixed file or directory names (e.g. .DS_Store, .git).

is_hidden_path(path: str | Path) -> bool
    True when any path component is a hidden file or directory name.

is_non_dicom_import_name(name: str) -> bool
    True for known non-DICOM sidecars and product cache trees skipped on import.

list_import_directory_files(root_dir: str | Path) -> list[str]
    List files under root_dir, skipping hidden names and non-DICOM sidecars.

ImportPathsError
    Raised when a DICOMDIR cannot be read during import expansion.

expand_import_directory(root_dir: str | Path) -> list[str]
    List files under root_dir; honor DICOMDIR when present.

count_studies_series_images(patient_path: str) -> tuple[int, int, int]
    Count studies, series, and images in a patient directory in the anonymizer store.

count_series(base_dir: str, patient_ids: Optional[list[str]]=None) -> int
    Count series across patients in the anonymizer store.

get_dcm_files(root_path: str | Path) -> list[Path]
    Collect .dcm paths under a patient, study, or series directory.

count_study_images(base_dir: Path, anon_pt_id: str, study_uid: str) -> int
    Count images stored under a study directory.

count_quarantine_images(quarantine_path: Path) -> int
    Count images stored in the quarantine directory.
"""
import logging
import os
from pathlib import Path
from typing import Optional

from pydicom import dcmread

logger = logging.getLogger(__name__)

DICOM_FILE_SUFFIX = ".dcm"

# Product cache trees under a series folder (must match controller/ai/tseg/config
# TSEG_CACHE_DIRNAME and ANNOTATIONS_DIRNAME — utils cannot import controller).
_IMPORT_SKIP_DIRNAMES = frozenset({"0_TS_SEG", "annotations"})

# Known non-DICOM sidecars; DICOM instances may be extensionless or .dcm.
_IMPORT_SKIP_SUFFIXES = (
    ".nii",
    ".nii.gz",
    ".nrrd",
    ".seg.nrrd",
    ".json",
    ".csv",
    ".txt",
    ".md",
    ".html",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".zip",
    ".xlsx",
    ".xls",
)


def is_hidden_name(name: str) -> bool:
    """True for dot-prefixed file or directory names (e.g. .DS_Store, .git)."""
    return bool(name) and name.startswith(".")


def is_hidden_path(path: str | Path) -> bool:
    """True when any path component is a hidden file or directory name."""
    return any(is_hidden_name(part) for part in Path(path).parts)


def is_non_dicom_import_name(name: str) -> bool:
    """
    True for known non-DICOM sidecars and product cache trees skipped on import.

    Args:
        name: File or directory basename (not a full path).

    Returns:
        True when the name should not be walked or imported as DICOM.
    """
    if not name or name in _IMPORT_SKIP_DIRNAMES:
        return True
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in _IMPORT_SKIP_SUFFIXES)


def list_import_directory_files(root_dir: str | Path) -> list[str]:
    """List files under root_dir, skipping hidden names and non-DICOM sidecars."""
    root = os.fspath(root_dir)
    file_paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames if not is_hidden_name(name) and not is_non_dicom_import_name(name)
        ]
        for filename in filenames:
            if is_hidden_name(filename) or is_non_dicom_import_name(filename):
                continue
            file_paths.append(os.path.join(dirpath, filename))
    return file_paths


class ImportPathsError(Exception):
    """Raised when expanding an import directory fails (e.g. bad DICOMDIR)."""


def expand_import_directory(root_dir: str | Path) -> list[str]:
    """
    Expand a directory to importable file paths (DICOMDIR-aware).

    When a DICOMDIR file is present, referenced image paths are collected from
    the directory records. Otherwise the tree is walked with
    list_import_directory_files.

    Args:
        root_dir: Directory to expand.

    Returns:
        Path strings suitable for anonymize_file / import_paths.

    Raises:
        ImportPathsError: When a DICOMDIR exists but cannot be read.
    """
    root = os.fspath(root_dir)
    dicomdir_file = os.path.join(root, "DICOMDIR")
    if not os.path.exists(dicomdir_file):
        return list_import_directory_files(root)

    file_paths: list[str] = []
    try:
        ds = dcmread(fp=dicomdir_file)
        resolved_root = str(Path(str(ds.filename)).resolve().parent)
        logger.info("Reading DICOMDIR root directory: %s", Path(resolved_root).stem)

        for patient in ds.patient_records:
            logger.info(
                "PATIENT: PatientID=%s, PatientName=%s",
                patient.PatientID,
                patient.PatientName,
            )
            studies = [ii for ii in patient.children if ii.DirectoryRecordType == "STUDY"]
            for study in studies:
                descr = study.StudyDescription or "(no value available)"
                logger.info(
                    "  STUDY: StudyID=%s, StudyDate=%s, StudyDescription=%s",
                    study.StudyID,
                    study.StudyDate,
                    descr,
                )
                all_series = [ii for ii in study.children if ii.DirectoryRecordType == "SERIES"]
                for series in all_series:
                    images = [ii for ii in series.children if ii.DirectoryRecordType == "IMAGE"]
                    plural = ("", "s")[len(images) > 1]
                    series_descr = getattr(series, "SeriesDescription", "(no value available)")
                    logger.info(
                        "    SERIES: SeriesNumber=%s, Modality=%s, SeriesDescription=%s - "
                        "%s SOP Instance%s",
                        series.SeriesNumber,
                        series.Modality,
                        series_descr,
                        len(images),
                        plural,
                    )
                    elems = [ii["ReferencedFileID"] for ii in images]
                    path_parts: list[list[str]] = []
                    for element in elems:
                        if element.VM == 1:
                            path_parts.append([str(element.value)])
                        else:
                            path_parts.append([str(part) for part in element.value])
                    image_paths = [
                        f"{resolved_root}/{Path(*parts)}" for parts in path_parts
                    ]
                    for fp in image_paths:
                        if is_hidden_path(fp):
                            continue
                        logger.info("      IMAGE: Path=%s", os.fspath(fp))
                        file_paths.append(fp)
    except Exception as exc:
        raise ImportPathsError(f"{dicomdir_file}, {exc}") from exc
    return file_paths


def count_studies_series_images(patient_path: str) -> tuple[int, int, int]:
    """
    Count studies, series, and images in a patient directory in the anonymizer store.

    Args:
        patient_path: Path to the patient directory.

    Returns:
        (study_count, series_count, image_count).
    """
    study_count = 0
    series_count = 0
    image_count = 0

    for root, dirs, files in os.walk(patient_path):
        if root == patient_path:
            study_count += len(dirs)
        else:
            series_count += len(dirs)
        for file in files:
            if file.endswith(DICOM_FILE_SUFFIX):
                image_count += 1

    return study_count, series_count, image_count


def count_series(base_dir: str, patient_ids: Optional[list[str]] = None) -> int:
    """
    Count series across patients in the anonymizer store.

    Args:
        base_dir: Base directory containing patient folders.
        patient_ids: Patient IDs to include; None means all patients.

    Returns:
        Total series count.
    """
    total_series = 0

    base_path = Path(base_dir)
    if not base_path.is_dir():
        raise ValueError(f"{base_dir} is not a valid directory")

    if patient_ids is None:
        patient_ids = [str(object=p) for p in base_path.iterdir() if p.is_dir()]

    for patient_id in patient_ids:
        patient_path: Path = base_path / patient_id
        if not patient_path.exists():
            continue

        for root, dirs, _files in os.walk(patient_path):
            if root != str(object=patient_path):
                total_series += len(dirs)

    return total_series


def get_dcm_files(root_path: str | Path) -> list[Path]:
    """
    Collect .dcm paths under a patient, study, or series directory.

    Args:
        root_path: Root path to search.

    Returns:
        List of DICOM file paths.
    """
    root_path = Path(root_path)

    return [
        Path(root) / file for root, _, files in os.walk(root_path) for file in files if file.endswith(DICOM_FILE_SUFFIX)
    ]


def count_study_images(base_dir: Path, anon_pt_id: str, study_uid: str) -> int:
    """
    Count images stored under a study directory.

    Args:
        base_dir: Images root (e.g. project public dir).
        anon_pt_id: Anonymized patient ID.
        study_uid: Study UID directory name.

    Returns:
        Image count.
    """
    study_path = Path(base_dir, anon_pt_id, study_uid)
    image_count = 0

    for _root, _dirs, files in os.walk(study_path):
        for file in files:
            if file.endswith(DICOM_FILE_SUFFIX):
                image_count += 1

    return image_count


def count_quarantine_images(quarantine_path: Path) -> int:
    """
    Count images stored in the quarantine directory.

    Args:
        quarantine_path: Quarantine folder path.

    Returns:
        Image count, or 0 if the path is missing.
    """
    if not quarantine_path.is_dir():
        return 0

    image_count = 0
    for _root, _dirs, files in os.walk(quarantine_path):
        for file in files:
            if file.__contains__(DICOM_FILE_SUFFIX):
                image_count += 1

    return image_count
