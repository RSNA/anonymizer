# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
from pydicom.dataset import Dataset
from pydicom.data import get_testdata_file
from controller.anonymize import uid_lookup, patient_id_lookup
from tests.helpers import (
    start_local_storage_scp,
    echo_local_storage_scp,
    send_file_to_scp,
    local_storage_dir,
)
from model.project import UIDROOT, SITEID, PROJECTNAME, TRIALNAME
from tests.dcm_tst_files import (
    cr1_filename,
    cr1_SOPInstanceUID,
    cr1_StudyInstanceUID,
    cr1_SeriesInstanceUID,
    ct_small_filename,
    ct_small_SOPInstanceUID,
    ct_small_SeriesInstanceUID,
    ct_small_StudyInstanceUID,
    ct_small_patient_name,
    ct_small_patient_id,
    mr_small_filename,
    mr_small_SeriesInstanceUID,
    mr_small_StudyInstanceUID,
    mr_small_patient_name,
    mr_small_patient_id,
)

logger = logging.getLogger(__name__)


def test_echo(temp_dir):
    start_local_storage_scp(temp_dir)
    echo_local_storage_scp()


def test_send_cr1(temp_dir):
    start_local_storage_scp(temp_dir)
    send_file_to_scp(cr1_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == "DEFAULT-SITE-000001"
    assert uid_lookup[cr1_SOPInstanceUID] == f"{UIDROOT}.{SITEID}.{1}"
    assert uid_lookup[cr1_StudyInstanceUID] == f"{UIDROOT}.{SITEID}.{2}"
    assert uid_lookup[cr1_SeriesInstanceUID] == f"{UIDROOT}.{SITEID}.{3}"


def test_send_ct_small(temp_dir):
    start_local_storage_scp(temp_dir)
    send_file_to_scp(ct_small_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == "DEFAULT-SITE-000001"
    assert uid_lookup[ct_small_SOPInstanceUID] == f"{UIDROOT}.{SITEID}.{1}"
    assert uid_lookup[ct_small_StudyInstanceUID] == f"{UIDROOT}.{SITEID}.{2}"
    assert uid_lookup[ct_small_SeriesInstanceUID] == f"{UIDROOT}.{SITEID}.{3}"


def test_send_mr_small(temp_dir):
    start_local_storage_scp(temp_dir)
    send_file_to_scp(mr_small_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == "DEFAULT-SITE-000001"
    ds = get_testdata_file(mr_small_filename, read=True)
    assert isinstance(ds, Dataset)
    assert uid_lookup[ds.SOPInstanceUID] == f"{UIDROOT}.{SITEID}.{1}"
    assert uid_lookup[ds.StudyInstanceUID] == f"{UIDROOT}.{SITEID}.{2}"
    assert uid_lookup[ds.SeriesInstanceUID] == f"{UIDROOT}.{SITEID}.{3}"


# TODO: test with multiple files, see CT2N, CT5N, MR2N dirs of pydicom test data
# def test_send_ct2n(temp_dir):
#     start_local_storage_scp(temp_dir)
#     send_file_to_scp(ct_small_filename, False)
#     dirlist = os.listdir(local_storage_dir(temp_dir))
#     assert len(dirlist) == 1
#     assert dirlist[0] == "DEFAULT-SITE-000001"
