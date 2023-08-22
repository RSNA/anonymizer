from tests.controller.helpers import (
    start_pacs_simulator_scp,
    echo_pacs_simulator_scp,
    start_local_storage_scp,
    echo_local_storage_scp,
)


def test_echo_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    echo_pacs_simulator_scp()


def test_echo(temp_dir: str):
    start_local_storage_scp(temp_dir)
    echo_local_storage_scp()
