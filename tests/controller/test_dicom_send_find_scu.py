import os

from tests.controller.helpers import (
    start_pacs_simulator_scp,
    send_file_to_scp,
    find_all_studies_on_test_pacs_scp,
    pacs_storage_dir,
)
from tests.controller.dcm_tst_files import (
    ct_small_filename,
    ct_small_SeriesInstanceUID,
    ct_small_patient_name,
    ct_small_patient_id,
    mr_small_filename,
    mr_small_SeriesInstanceUID,
    mr_small_patient_name,
    mr_small_patient_id,
)


def test_send_1_CT_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ct_small_SeriesInstanceUID + ".1.dcm"


def test_send_1_MR_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(mr_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == mr_small_SeriesInstanceUID + ".1.dcm"


def test_send_2_files_find_all_studies_on_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(ct_small_filename, True)
    send_file_to_scp(mr_small_filename, True)
    results = find_all_studies_on_test_pacs_scp()
    assert results
    assert len(results) == 2
    assert (
        results[0].PatientName == ct_small_patient_name
        or results[1].PatientName == ct_small_patient_name
    )
    assert (
        results[0].PatientID == ct_small_patient_id
        or results[1].PatientID == ct_small_patient_id
    )
    assert (
        results[1].PatientName == mr_small_patient_name
        or results[0].PatientName == mr_small_patient_name
    )
    assert (
        results[1].PatientID == mr_small_patient_id
        or results[0].PatientID == mr_small_patient_id
    )
