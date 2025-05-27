from dicom_test_nodes import LocalStorageSCP, PACSSimulatorSCP


def test_echo_pacs_simulator(controller):
    assert controller.echo(PACSSimulatorSCP.aet)


def test_echo_local_storage(controller):
    assert controller.echo(LocalStorageSCP.aet)
