# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import time
from pydicom.dataset import Dataset
from tests.controller.helpers import send_file_to_scp
from tests.controller.dicom_test_files import (
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
)
from tests.controller.dicom_test_nodes import TEST_SITEID, TEST_UIDROOT, LocalStorageSCP


def test_send_cr1(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(cr1_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"
    assert controller.anonymizer.model.get_anon_uid(ds.StudyInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{1}"
    assert controller.anonymizer.model.get_anon_uid(ds.SeriesInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{2}"
    assert controller.anonymizer.model.get_anon_uid(ds.SOPInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{3}"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel


def test_send_ct_small(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    assert controller.anonymizer.model.get_anon_uid(ds.StudyInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{1}"
    assert controller.anonymizer.model.get_anon_uid(ds.SeriesInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{2}"
    assert controller.anonymizer.model.get_anon_uid(ds.SOPInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{3}"


def test_send_mr_small(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(mr_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    assert isinstance(ds, Dataset)
    assert controller.anonymizer.model.get_anon_uid(ds.StudyInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{1}"
    assert controller.anonymizer.model.get_anon_uid(ds.SeriesInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{2}"
    assert controller.anonymizer.model.get_anon_uid(ds.SOPInstanceUID) == f"{TEST_UIDROOT}.{TEST_SITEID}.{3}"
