from controller.dicom_ae import DICOMNode

LocalSCU = DICOMNode("127.0.0.1", 0, "ANONSCU", False)
LocalStorageSCP = DICOMNode("127.0.0.1", 1041, "ANONSCP", True)
PACSSimulatorSCP = DICOMNode("127.0.0.1", 1042, "TESTPACS", True)
