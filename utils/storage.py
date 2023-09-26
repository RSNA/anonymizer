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
