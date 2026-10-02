"""Simulator edge cases for C-FIND SCU (no Orthanc)."""

from __future__ import annotations

import time
from queue import Empty, Queue

from pydicom.dataset import Dataset

from anonymizer.controller.dicom.requests import FindStudyRequest, FindStudyResponse
from anonymizer.controller.project import ProjectController
from anonymizer.utils.dicom import C_FAILURE, C_SUCCESS
from tests.controller.dicom.support.helpers import send_file_to_scp, send_files_to_scp
from tests.controller.dicom.support.test_files import (
    CT_STUDY_1_SERIES_4_IMAGES,
    ct_small_StudyInstanceUID,
    ct_small_filename,
    patient1_id,
    patient3_id,
)
from tests.controller.dicom.support.test_nodes import PACSSimulatorSCP


def test_find_studies_unknown_remote_scp(controller: ProjectController) -> None:
    # Errors are latched into an empty result list (and optionally ux_Q); do not raise.
    results = controller.find_studies(
        scp_name="DOES_NOT_EXIST",
        name="",
        id="",
        acc_no="",
        study_date="",
        modality="",
        ux_Q=None,
        verify_attributes=False,
    )
    assert results == []


def test_find_studies_empty_pacs_returns_empty_list(controller: ProjectController) -> None:
    results = controller.find_studies(
        scp_name=PACSSimulatorSCP.aet,
        name="",
        id="",
        acc_no="",
        study_date="",
        modality="",
        ux_Q=None,
        verify_attributes=False,
    )
    assert results == [] or results is None or len(results) == 0


def test_find_studies_via_acc_nos_exact_match(controller: ProjectController) -> None:
    dsets = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    acc = str(dsets[0].AccessionNumber)
    results = controller.find_studies_via_acc_nos(
        scp_name=PACSSimulatorSCP.aet,
        acc_no_list=[acc, "ZZZ-NO-MATCH"],
        ux_Q=None,
        verify_attributes=False,
    )
    assert results
    assert all(str(r.AccessionNumber) == acc for r in results)
    assert any(r.StudyInstanceUID == dsets[0].StudyInstanceUID for r in results)


def test_find_ex_delivers_ux_queue_and_abort(controller: ProjectController) -> None:
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    ux_Q: Queue = Queue()
    req = FindStudyRequest(
        scp_name=PACSSimulatorSCP.aet,
        name="",
        id="",
        acc_no="",
        study_date="",
        modality="",
        ux_Q=ux_Q,
    )
    controller.find_ex(req)
    deadline = time.time() + 10
    got: list[FindStudyResponse] = []
    while time.time() < deadline:
        try:
            got.append(ux_Q.get(timeout=0.2))
            if got[-1].study_result is None and getattr(got[-1].status, "Status", None) == C_SUCCESS:
                break
        except Empty:
            continue
    assert got
    assert any(isinstance(r, FindStudyResponse) for r in got)


def test_get_study_uid_hierarchy_series_and_instance_levels(controller: ProjectController) -> None:
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    err, series_only = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id, False
    )
    assert err is None
    assert series_only.get_number_of_instances() >= 1
    assert all(len(s.instances) == 0 for s in series_only.series.values())

    err2, with_inst = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id, True
    )
    assert err2 is None
    assert with_inst.get_number_of_instances() >= 1
    assert sum(len(s.instances) for s in with_inst.series.values()) >= 1


def test_get_number_of_pending_instances_after_hierarchy(controller: ProjectController) -> None:
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    err, study = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id, True
    )
    assert err is None
    pending = controller.get_number_of_pending_instances(study)
    assert pending == study.get_number_of_instances()


def test_find_studies_with_patient_id_filter(controller: ProjectController) -> None:
    send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    results = controller.find_studies(
        scp_name=PACSSimulatorSCP.aet,
        name="",
        id=patient1_id,
        acc_no="",
        study_date="",
        modality="CT",
        ux_Q=None,
        verify_attributes=False,
    )
    assert results
    assert all(getattr(r, "PatientID", "") == patient1_id for r in results)


def test_query_helper_via_established_find_association(controller: ProjectController) -> None:
    """Exercise unused _query helper on a live Find association."""
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assoc = controller._connect_to_scp(PACSSimulatorSCP.aet, controller.get_study_root_find_contexts())
    try:
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = ct_small_StudyInstanceUID
        ds.PatientName = ""
        ds.PatientID = ""
        ds.AccessionNumber = ""
        ds.StudyDate = ""
        ds.ModalitiesInStudy = ""
        ds.NumberOfStudyRelatedSeries = ""
        ds.NumberOfStudyRelatedInstances = ""
        results = controller._query(assoc, ds, ux_Q=None, required_attributes=None)
        assert isinstance(results, list)
        assert any(getattr(r, "StudyInstanceUID", None) == ct_small_StudyInstanceUID for r in results)
    finally:
        if assoc.is_established:
            assoc.release()


def test_find_studies_unknown_remote_with_ux_queue(controller: ProjectController) -> None:
    ux_Q: Queue = Queue()
    results = controller.find_studies(
        scp_name="DOES_NOT_EXIST",
        name="",
        id="",
        acc_no="",
        study_date="",
        modality="",
        ux_Q=ux_Q,
        verify_attributes=False,
    )
    assert results == []
    resp = ux_Q.get(timeout=2)
    assert isinstance(resp, FindStudyResponse)
    assert resp.study_result is None
    assert getattr(resp.status, "Status", None) == C_FAILURE or getattr(resp.status, "ErrorComment", "")


def test_get_study_uid_hierarchies_batch(controller: ProjectController) -> None:
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    err, study = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id, False
    )
    assert err is None
    controller.get_study_uid_hierarchies(PACSSimulatorSCP.aet, [study], instance_level=True)
    assert study.get_number_of_instances() >= 1


def test_find_ex_via_accession_list(controller: ProjectController) -> None:
    dsets = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    acc = str(dsets[0].AccessionNumber)
    ux_Q: Queue = Queue()
    req = FindStudyRequest(
        scp_name=PACSSimulatorSCP.aet,
        name="",
        id="",
        acc_no=[acc],
        study_date="",
        modality="",
        ux_Q=ux_Q,
    )
    controller.find_ex(req)
    deadline = time.time() + 15
    got: list[FindStudyResponse] = []
    while time.time() < deadline:
        try:
            got.append(ux_Q.get(timeout=0.2))
            if got[-1].study_result is None and getattr(got[-1].status, "Status", None) == C_SUCCESS:
                break
        except Empty:
            continue
    assert got


def test_abort_query_flag(controller: ProjectController) -> None:
    controller.abort_query()
    assert controller._abort_query is True
    controller._abort_query = False


def test_query_helper_with_required_attributes_miss(controller: ProjectController) -> None:
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assoc = controller._connect_to_scp(PACSSimulatorSCP.aet, controller.get_study_root_find_contexts())
    try:
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = ct_small_StudyInstanceUID
        ds.PatientName = ""
        ds.PatientID = ""
        ds.AccessionNumber = ""
        ds.StudyDate = ""
        ds.ModalitiesInStudy = ""
        results = controller._query(
            assoc,
            ds,
            ux_Q=None,
            required_attributes=["PatientName", "WindowCenter"],
        )
        assert isinstance(results, list)
    finally:
        if assoc.is_established:
            assoc.release()
