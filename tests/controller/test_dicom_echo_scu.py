from dicom_test_nodes import LocalStorageSCP, PACSSimulatorSCP


def test_echo_pacs_simulator(temp_dir: str, controller):
    controller.echo(PACSSimulatorSCP.aet)


def test_echo_local_storage(temp_dir: str, controller):
    controller.echo(LocalStorageSCP.aet)
