import os
from pathlib import Path
from pydicom import Dataset


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
