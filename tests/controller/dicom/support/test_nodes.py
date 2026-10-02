from anonymizer.model.project import DICOMNode
from tests.controller.dicom.support.orthanc_bundle import (
    DICOM_PORT,
    HTTP_PORT,
    ORTHANC_AET,
    ORTHANC_PASSWORD,
    ORTHANC_USER,
)

LocalSCU = DICOMNode("127.0.0.1", 0, "ANONYMIZER", True)
LocalStorageSCP = DICOMNode("127.0.0.1", 1045, "ANONYMIZER", True)
PACSSimulatorSCP = DICOMNode("127.0.0.1", 1046, "TESTPACS", False)
# Managed Orthanc (tests download+start): dedicated ports so host Orthanc on 4242/8042 can coexist
OrthancSCP = DICOMNode("127.0.0.1", DICOM_PORT, ORTHANC_AET, False)
OrthancDicomWeb = DICOMNode(
    "127.0.0.1",
    DICOM_PORT,
    ORTHANC_AET,
    False,
    dicomweb=True,
    http_port=HTTP_PORT,
    http_path="/dicom-web",
    use_https=False,
    username=ORTHANC_USER,
    password=ORTHANC_PASSWORD,
)

RemoteSCPDict: dict[str, DICOMNode] = {
    PACSSimulatorSCP.aet: PACSSimulatorSCP,
    OrthancSCP.aet: OrthancSCP,
    LocalStorageSCP.aet: LocalStorageSCP,
}

# Default project globals:
TEST_SITEID = "99.99"
TEST_PROJECTNAME = "ANONYMIZER_UNIT_TEST"
TEST_UIDROOT = "1.2.826.0.1.3680043.10.474"
