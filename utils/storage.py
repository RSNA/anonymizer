import os
from pathlib import Path
from turtle import st
from pydicom import Dataset


def local_storage_path(base_dir: Path, siteid: str, ds: Dataset) -> Path:
    study_uid = str(ds.StudyInstanceUID)
    if not "." in study_uid:
        study_suffix = "INVALID"
    else:
        study_suffix = study_uid.rsplit(".", 1)[-1]
    dest_path = Path(
        base_dir,
        str(ds.PatientName),
        "Study" + "-" + ds.Modality + "-" + ds.AccessionNumber + "-" + study_suffix,
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
