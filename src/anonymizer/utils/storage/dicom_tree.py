"""Anonymized store tree: DICOM listing, counts, and hidden-path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DICOM_FILE_SUFFIX = ".dcm"


def is_hidden_name(name: str) -> bool:
    """True for dot-prefixed file or directory names (e.g. ``.DS_Store``, ``.git``)."""
    return bool(name) and name.startswith(".")


def is_hidden_path(path: str | Path) -> bool:
    """True when any path component is a hidden file or directory name."""
    return any(is_hidden_name(part) for part in Path(path).parts)


def list_import_directory_files(root_dir: str | Path) -> list[str]:
    """List files under ``root_dir``, skipping hidden directories and files."""
    root = os.fspath(root_dir)
    file_paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not is_hidden_name(name)]
        for filename in filenames:
            if is_hidden_name(filename):
                continue
            file_paths.append(os.path.join(dirpath, filename))
    return file_paths


def count_studies_series_images(patient_path: str) -> tuple[int, int, int]:
    """
    Count studies, series, and images in a patient directory in the anonymizer store.

    Args:
        patient_path: Path to the patient directory.

    Returns:
        ``(study_count, series_count, image_count)``.
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
    Collect ``.dcm`` paths under a patient, study, or series directory.

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
