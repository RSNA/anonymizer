from model.project import DICOMNode

LocalSCU = DICOMNode("127.0.0.1", 0, "ANONYMIZER", True)
LocalStorageSCP = DICOMNode("127.0.0.1", 1045, "ANONYMIZER", True)
PACSSimulatorSCP = DICOMNode("127.0.0.1", 1046, "TESTPACS", False)
OrthancSCP = DICOMNode("127.0.0.1", 4242, "ORTHANC", False)

RemoteSCPDict = {
    PACSSimulatorSCP.aet: PACSSimulatorSCP,
    OrthancSCP.aet: OrthancSCP,
    LocalStorageSCP.aet: LocalStorageSCP,
}

# Default project globals:
TEST_SITEID = "99.99"
TEST_PROJECTNAME = "ANONYMIZER_UNIT_TEST"
TEST_UIDROOT = "1.2.826.0.1.3680043.10.474"
