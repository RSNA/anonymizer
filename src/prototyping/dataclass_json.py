import os
from pathlib import Path
import shutil
import json
import tempfile
from logging import WARNING
from anonymizer.model.project import ProjectModel, NetworkTimeouts, LoggingLevels
from anonymizer.model.project import DICOMNode


LocalSCU = DICOMNode("127.0.0.1", 0, "ANONYMIZER", True)
LocalStorageSCP = DICOMNode("127.0.0.1", 1045, "ANONYMIZER", True)
PACSSimulatorSCP = DICOMNode("127.0.0.1", 1046, "TESTPACS", False)
OrthancSCP = DICOMNode("127.0.0.1", 4242, "ORTHANC", False)

RemoteSCPDict: dict[str, DICOMNode] = {
    PACSSimulatorSCP.aet: PACSSimulatorSCP,
    OrthancSCP.aet: OrthancSCP,
    LocalStorageSCP.aet: LocalStorageSCP,
}

# Default project globals:
TEST_SITEID = "99.99"
TEST_PROJECTNAME = "ANONYMIZER_UNIT_TEST"
TEST_UIDROOT = "1.2.826.0.1.3680043.10.474"

anon_store = Path(tempfile.mkdtemp(), LocalSCU.aet)
# Make sure storage directory exists:
os.makedirs(anon_store, exist_ok=True)
# Create Test ProjectModel:
project_model = ProjectModel(
    site_id=TEST_SITEID,
    project_name=TEST_PROJECTNAME,
    uid_root=TEST_UIDROOT,
    remove_pixel_phi=False,
    storage_dir=anon_store,
    scu=LocalSCU,
    scp=LocalStorageSCP,
    remote_scps=RemoteSCPDict,
    network_timeouts=NetworkTimeouts(2, 5, 5, 15),
    anonymizer_script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
    logging_levels=LoggingLevels(anonymizer=WARNING, pynetdicom=WARNING, pydicom=False),
)

# Serialize to JSON
json_data = project_model.to_json(indent=4)  # Get JSON string
print(json_data)

# Deserialize from JSON
project_model_from_json = ProjectModel.from_json(json_data)  # Load from JSON string
print(project_model_from_json)
