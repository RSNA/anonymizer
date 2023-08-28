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
        + str(ds.StudyDate)
        + "T"
        + str(ds.StudyTime)[:6],  # TODO: 4 digit magic number at end, checksum?
        "Series" + "-" + str(ds.SeriesNumber),
        "Image" + "-" + str(ds.InstanceNumber) + ".dcm",
    )
    # Ensure all directories in the path exist
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    return dest_path


def count_dcm_files(root_path):
    count = 0
    for root, _, files in os.walk(root_path):
        for file in files:
            if file.endswith(".dcm"):
                count += 1
    return count
