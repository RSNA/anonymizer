import os
from pathlib import Path
from unittest.mock import DEFAULT
from pydicom import Dataset

DEFAULT_LOCAL_STORAGE_DIR = os.path.join(os.path.expanduser("~"), "ANONYMIZER_STORE")


def local_storage_path(base_dir: str, siteid: str, ds: Dataset) -> Path:
    dest_path = Path(
        base_dir,
        str(ds.PatientName),
        "Study"
        + "-"
        + ds.Modality
        + "-"
        + ds.AccessionNumber
        + "-"
        + str(ds.StudyInstanceUID[-4:]),
        "Series" + "-" + str(ds.SeriesNumber),
        "Image" + "-" + str(ds.InstanceNumber) + ".dcm",
    )
    # Ensure all directories in the path exist
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    return dest_path


def count_dcm_files_and_studies(patient_path: str):
    study_count = 0
    file_count = 0

    for root, dirs, files in os.walk(patient_path):
        if root == patient_path:
            study_count += len(dirs)
        for file in files:
            if file.endswith(".dcm"):
                file_count += 1

    return study_count, file_count
