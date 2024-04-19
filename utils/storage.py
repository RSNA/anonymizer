from email.mime import base
import os
from pathlib import Path
from turtle import st
from pydicom import Dataset

# TODO: move these to controller or model?


def local_storage_path(base_dir: Path, ds: Dataset) -> Path:
    assert base_dir
    assert hasattr(ds, "PatientID")
    assert hasattr(ds, "StudyInstanceUID")
    assert hasattr(ds, "SeriesInstanceUID")
    assert hasattr(ds, "SOPInstanceUID")

    dest_path = Path(
        base_dir,
        ds.PatientID,
        ds.StudyInstanceUID,
        ds.SeriesInstanceUID,
        ds.SOPInstanceUID + ".dcm",
    )
    # Ensure all directories in the path exist
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    return dest_path


def get_latest_pkl_file(directory: str, filename_contains: str) -> str | None:
    """
    This function finds the latest *.pkl file (by modification time) within a directory
    that also contains the specified string in its filename.

    Args:
        directory (str): Path to the directory containing the pickle files.
        filename_contains (str): String to search for within the filenames.

    Returns:
        str: Path to the latest *.pkl file matching the criteria, or None if no match is found.
    """
    latest_file = None
    latest_mtime = None

    for filename in os.listdir(path=directory):
        if filename.endswith(".pkl") and filename_contains in filename:
            filepath = os.path.join(directory, filename)
            mtime = os.path.getmtime(filename=filepath)  # Get modification time
            if latest_mtime is None or mtime > latest_mtime:
                latest_file = filepath
                latest_mtime = mtime

    return latest_file


def count_studies_series_images(patient_path: str):
    """
    Counts the number of studies, series, and images in a given patient directory.

    Args:
        patient_path (str): The path to the patient directory.

    Returns:
        A tuple containing the number of studies, series, and images in the patient directory.
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
            if file.endswith(".dcm"):
                image_count += 1

    return study_count, series_count, image_count


def count_study_images(base_dir: Path, anon_pt_id: str, study_uid: str) -> int:
    """
    Counts the number of images stored in a given study directory.

    Args:
        anon_uid (str): The anonymous patient ID.
        study_uid (str): The study UID.

    Returns:
        The number of images stored in the study directory.
    """
    study_path = Path(base_dir, anon_pt_id, study_uid)
    image_count = 0

    for _, _, files in os.walk(study_path):
        for file in files:
            if file.endswith(".dcm"):
                image_count += 1

    return image_count
