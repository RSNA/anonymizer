import os
from pathlib import Path
from pydicom import FileDataset


def local_storage_path(base_dir: str, siteid: str, ds: FileDataset) -> Path:
    dest_path = Path(
        base_dir,
        siteid,
        str(ds.PatientName),
        "Study"
        + "-"
        + ds.Modality
        + "-"
        + str(ds.StudyDate),  # TODO: magic number at end
        "Series" + "-" + str(ds.SeriesNumber),
        "Image" + "-" + str(ds.InstanceNumber) + ".dcm",
    )
    # Ensure all directories in the path exist
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    return dest_path
