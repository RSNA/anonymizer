import os
from pydicom.dataset import Dataset

from tests.controller.helpers import (
    start_pacs_simulator_scp,
    send_file_to_scp,
    find_all_studies_on_pacs_simulator_scp,
    pacs_storage_dir,
)
from tests.controller.dcm_tst_files import (
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
)


def test_send_1_CR_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(cr1_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"


def test_send_1_CT_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"


def test_send_1_MR_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(mr_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"


def test_send_2_files_find_all_studies_on_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds1: Dataset = send_file_to_scp(ct_small_filename, True)
    ds2: Dataset = send_file_to_scp(mr_small_filename, True)

    results = find_all_studies_on_pacs_simulator_scp()
    assert results
    assert len(results) == 2

    # Extract PatientName and PatientID from the sent datasets
    sent_patient_names = set([ds1.PatientName, ds2.PatientName])
    sent_patient_ids = set([ds1.PatientID, ds2.PatientID])

    # Check that each result matches the PatientName and PatientID of a sent dataset
    for result in results:
        assert result.PatientName in sent_patient_names
        assert result.PatientID in sent_patient_ids
