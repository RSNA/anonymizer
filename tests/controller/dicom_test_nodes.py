from model.project import DICOMNode

LocalSCU = DICOMNode("127.0.0.1", 0, "ANONYMIZER", True)
LocalStorageSCP = DICOMNode("127.0.0.1", 1041, "ANONYMIZER", True)
PACSSimulatorSCP = DICOMNode("127.0.0.1", 1042, "TESTPACS", False)
ORTHANCSCP = DICOMNode("127.0.0.1", 8042, "ORTHANC", False)

# TODO: test more than one remote scp
RemoteSCPDict = {
    PACSSimulatorSCP.aet: PACSSimulatorSCP,
    ORTHANCSCP.aet: ORTHANCSCP,
    LocalStorageSCP.aet: LocalStorageSCP,
}

# Default project globals:
TEST_SITEID = "999999"
TEST_PROJECTNAME = "TEST-PROJECT"
TEST_TRIALNAME = "TEST-TRIAL"
TEST_UIDROOT = "1.2.826.0.1.3680043.10.474"
