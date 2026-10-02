"""Request / response dataclasses for ProjectController DICOM / export UX."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue

from pydicom import Dataset

from anonymizer.controller.dicom.hierarchies import StudyUIDHierarchy
from anonymizer.model.project import DICOMNode


@dataclass
class EchoRequest:
    scp: str | DICOMNode
    ux_Q: Queue


@dataclass
class EchoResponse:
    success: bool
    error: str | None


@dataclass
class FindStudyRequest:
    scp_name: str
    name: str
    id: str
    acc_no: str | list[str]
    study_date: str
    modality: str
    ux_Q: Queue


@dataclass
class FindStudyResponse:
    status: Dataset
    study_result: Dataset | None


@dataclass
class MoveStudiesRequest:
    scp_name: str
    dest_scp_ae: str
    level: str
    studies: list[StudyUIDHierarchy]  # Move process updates hierarchy, no MoveStudiesResponse
    force_move: bool = False  # test/hook: skip C-GET preference and use C-MOVE


@dataclass
class ExportPatientsRequest:
    dest_name: str
    patient_ids: list[str]  # list of patient IDs to export
    ux_Q: Queue  # queue for UX updates for the full export
    export_dicom_seg: bool = False


@dataclass
class ExportPatientsResponse:
    patient_id: str
    files_sent: int  # incremented for each file sent successfully
    error: str | None  # error message
    complete: bool

