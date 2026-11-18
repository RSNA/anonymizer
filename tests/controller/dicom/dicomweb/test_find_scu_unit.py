"""Mocked FindMixin DICOMweb / QIDO unit tests (no Orthanc)."""

from __future__ import annotations

from queue import Queue
from unittest.mock import MagicMock, patch

from pydicom import Dataset

from anonymizer.controller.dicom.find_scu import FindMixin
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import DICOMNode, NetworkTimeouts
from anonymizer.utils.dicom import C_FAILURE


def _node(**kwargs) -> DICOMNode:
    defaults = dict(
        ip="127.0.0.1",
        port=4242,
        aet="ORTHANC",
        local=False,
        dicomweb=True,
        http_port=8042,
        http_path="/dicom-web",
        username="user",
        password="pass",
    )
    defaults.update(kwargs)
    return DICOMNode(**defaults)


def _timeouts() -> NetworkTimeouts:
    return NetworkTimeouts(5, 30, 30, 60)


def _patch_open_session():
    return patch("anonymizer.controller.dicom.find_scu.dicomweb_api.open_session")


class FakeFind(FindMixin):
    def __init__(self) -> None:
        self.model = MagicMock()
        self.model.network_timeouts = _timeouts()
        self.model.remote_scps = {"QUERY": _node()}
        self.model.modalities = ["CT"]
        self.model.storage_classes = ["1.2.840.10008.5.1.4.1.1.2"]
        self._abort_query = False
        self._required_attributes_study_query = list(ProjectController._required_attributes_study_query)
        self._required_attributes_series_query = list(ProjectController._required_attributes_series_query)
        self._required_attributes_instance_query = list(ProjectController._required_attributes_instance_query)

    def _resolve_remote(self, scp):
        return self.model.remote_scps[scp]

    def _missing_attributes(self, required, ds):
        return [a for a in required if not hasattr(ds, a)]

    def _strip_query_result_fields(self, ds):
        return


def _valid_study(*, accession: str = "ACC1") -> Dataset:
    study = Dataset()
    study.StudyInstanceUID = "1.2.3"
    study.ModalitiesInStudy = "CT"
    study.NumberOfStudyRelatedSeries = 1
    study.NumberOfStudyRelatedInstances = 2
    study.AccessionNumber = accession
    return study


def test_find_acc_dedupe_and_partial_drop() -> None:
    fake = FakeFind()
    matching = _valid_study(accession="A")
    partial = _valid_study(accession="A*")
    calls: list[str] = []

    def find_studies(session, **kwargs):
        acc = kwargs.get("accession", "")
        calls.append(acc)
        if acc == "A":
            return [matching, partial]
        if acc == "B":
            return [_valid_study(accession="B")]
        return []

    with (
        patch(
            "anonymizer.controller.dicom.find_scu.dicomweb_api.find_studies",
            side_effect=find_studies,
        ),
        _patch_open_session() as open_sess,
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        results = fake._find_studies_via_acc_nos_dicomweb("QUERY", ["A", "A", "B", ""])

    assert set(calls) == {"A", "B"}
    assert {r.AccessionNumber for r in results} == {"A", "B"}


def test_find_abort_mid_acc_query() -> None:
    fake = FakeFind()
    ux: Queue = Queue()
    seen: list[str] = []

    def find_studies(session, **kwargs):
        acc = kwargs.get("accession", "")
        seen.append(acc)
        if len(seen) == 1:
            fake._abort_query = True
        return [_valid_study(accession=acc)]

    with (
        patch(
            "anonymizer.controller.dicom.find_scu.dicomweb_api.find_studies",
            side_effect=find_studies,
        ),
        _patch_open_session() as open_sess,
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        results = fake._find_studies_via_acc_nos_dicomweb(
            "QUERY", ["X", "Y"], ux_Q=ux
        )

    assert len(results) == 1
    fail = None
    while not ux.empty():
        item = ux.get_nowait()
        if item.status.Status == C_FAILURE:
            fail = item
    assert fail is not None
    assert "aborted" in fail.status.ErrorComment.lower()


def test_find_connection_failure() -> None:
    fake = FakeFind()
    ux: Queue = Queue()
    with (
        patch(
            "anonymizer.controller.dicom.find_scu.dicomweb_api.find_studies",
            side_effect=ConnectionError("refused"),
        ),
        _patch_open_session() as open_sess,
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        results = fake._find_studies_dicomweb("QUERY", "", "P", "", "", "", ux_Q=ux)
    assert results == []
    fail = ux.get_nowait()
    assert fail.status.Status == C_FAILURE


def test_hierarchy_modality_filter_and_instance_qido() -> None:
    fake = FakeFind()
    study_uid = "1.2.3.study"
    kept = Dataset()
    kept.StudyInstanceUID = study_uid
    kept.SeriesInstanceUID = "1.2.3.series"
    kept.Modality = "CT"
    kept.NumberOfSeriesRelatedInstances = 0
    dropped = Dataset()
    dropped.StudyInstanceUID = study_uid
    dropped.SeriesInstanceUID = "1.2.3.series.us"
    dropped.Modality = "US"
    dropped.NumberOfSeriesRelatedInstances = 5

    inst = Dataset()
    inst.StudyInstanceUID = study_uid
    inst.SeriesInstanceUID = "1.2.3.series"
    inst.SOPInstanceUID = "1.2.3.sop"

    with (
        patch(
            "anonymizer.controller.dicom.find_scu.dicomweb_api.find_series",
            return_value=[kept, dropped],
        ),
        patch(
            "anonymizer.controller.dicom.find_scu.dicomweb_api.find_instances",
            return_value=[inst],
        ) as find_inst,
        _patch_open_session() as open_sess,
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        err, hier = fake._get_study_uid_hierarchy_dicomweb("QUERY", study_uid, "P1")

    assert err is None
    assert set(hier.series) == {"1.2.3.series"}
    find_inst.assert_called_once()
    assert hier.series["1.2.3.series"].instance_count == 1
    assert "1.2.3.sop" in hier.series["1.2.3.series"].instances
