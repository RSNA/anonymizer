import os
from pathlib import Path
from turtle import st
from pydicom import Dataset

# TODO: move these to controller or model?


def local_storage_path(base_dir: Path, ds: Dataset) -> Path:
    study_uid = str(ds.StudyInstanceUID)
    if not "." in study_uid:
        study_suffix = "INVALID"
    else:
        study_suffix = study_uid.rsplit(".", 1)[-1]
    dest_path = Path(
        base_dir,
        str(ds.PatientName),
        "Study" + "-" + ds.AccessionNumber + "-" + study_suffix,
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


def images_stored(base_dir: Path, anon_pt_id: str, study_uid: str, acc_no: str) -> int:
    """
    Counts the number of images stored in a given study directory.

    Args:
        anon_uid (str): The anonymous patient ID.
        study_uid (str): The study UID.

    Returns:
        The number of images stored in the study directory.
    """
    ds: Dataset = Dataset()
    ds.StudyInstanceUID = study_uid
    ds.PatientID = anon_pt_id
    ds.PatientName = anon_pt_id
    ds.AccessionNumber = acc_no
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    instance_path = local_storage_path(base_dir, ds)
    study_path = instance_path.parent.parent
    image_count = 0
    for root, dirs, files in os.walk(study_path):
        for file in files:
            if file.endswith(".dcm"):
                image_count += 1
    return image_count
