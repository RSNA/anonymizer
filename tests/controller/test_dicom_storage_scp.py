# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
from pydicom.dataset import Dataset
from pydicom.data import get_testdata_file
from controller.anonymize import uid_lookup
from tests.controller.helpers import (
    start_local_storage_scp,
    send_file_to_scp,
    local_storage_dir,
)
from model.project import UIDROOT, SITEID
from tests.controller.dcm_tst_files import (
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
)

logger = logging.getLogger(__name__)


def test_send_cr1(temp_dir: str):
    start_local_storage_scp(temp_dir)
    ds: Dataset = send_file_to_scp(cr1_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == SITEID + "-000001"
    assert uid_lookup[ds.SOPInstanceUID] == f"{UIDROOT}.{SITEID}.{1}"
    assert uid_lookup[ds.StudyInstanceUID] == f"{UIDROOT}.{SITEID}.{2}"
    assert uid_lookup[ds.SeriesInstanceUID] == f"{UIDROOT}.{SITEID}.{3}"


def test_send_ct_small(temp_dir: str):
    start_local_storage_scp(temp_dir)
    ds: Dataset = send_file_to_scp(ct_small_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == SITEID + "-000001"
    assert uid_lookup[ds.SOPInstanceUID] == f"{UIDROOT}.{SITEID}.{1}"
    assert uid_lookup[ds.StudyInstanceUID] == f"{UIDROOT}.{SITEID}.{2}"
    assert uid_lookup[ds.SeriesInstanceUID] == f"{UIDROOT}.{SITEID}.{3}"


def test_send_mr_small(temp_dir: str):
    start_local_storage_scp(temp_dir)
    ds: Dataset = send_file_to_scp(mr_small_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == SITEID + "-000001"
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
