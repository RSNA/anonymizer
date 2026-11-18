"""Mocked RetrieveMixin WADO / QR probe unit tests (no Orthanc)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.dicom.hierarchies import (
    InstanceUIDHierarchy,
    SeriesUIDHierarchy,
    StudyUIDHierarchy,
)
from anonymizer.controller.dicom.requests import MoveStudiesRequest
from anonymizer.controller.dicom.retrieve_scu import RetrieveMixin
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import DICOMNode, NetworkTimeouts
from pydicom import Dataset


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


class FakeRetrieve(RetrieveMixin):
    def __init__(self, *, dicomweb: bool = True) -> None:
        self.model = MagicMock()
        self.model.network_timeouts = _timeouts()
        self.model.remote_scps = {
            "DW": _node(dicomweb=dicomweb),
            "DIMSE": _node(dicomweb=False, aet="DIMSE"),
        }
        self.anonymizer = MagicMock()
        self.anonymizer.model.get_pending_instance_count.return_value = 2
        self.anonymizer.model.series_complete.return_value = False
        self.anonymizer.model.instance_received.return_value = False
        self._abort_move = False
        self._qr_get_supported: dict[str, bool] = {}
        self._qr_move_supported: dict[str, bool] = {}
        self._STUDY_ROOT_QR_CLASSES = list(ProjectController._STUDY_ROOT_QR_CLASSES)
        self._handle_store_time_slice_interval = 0
        self._study_move_thread_pool_size = 1
        self._move_futures = None
        self._move_executor = None
        self._last_retrieve_modality = None

    def _resolve_remote(self, scp):
        if isinstance(scp, DICOMNode):
            return scp
        return self.model.remote_scps[scp]

    def get_study_root_get_contexts(self):
        return []

    def get_study_root_move_contexts(self):
        return []

    def _storage_scp_roles(self):
        return None

    def _connect_to_scp(self, *args, **kwargs):
        raise RuntimeError("probe fail")


def _study(*, instance_count: int = 2) -> StudyUIDHierarchy:
    series = SeriesUIDHierarchy(
        uid="1.2.series",
        modality="CT",
        instance_count=instance_count,
        instances={
            "1.2.sop1": InstanceUIDHierarchy(uid="1.2.sop1", number=1),
            "1.2.sop2": InstanceUIDHierarchy(uid="1.2.sop2", number=2),
        },
    )
    return StudyUIDHierarchy(uid="1.2.study", ptid="P1", series={"1.2.series": series})


def test_normalize_retrieve_level() -> None:
    fake = FakeRetrieve()
    assert fake._normalize_retrieve_level(None) == "SERIES"
    assert fake._normalize_retrieve_level("") == "SERIES"
    assert fake._normalize_retrieve_level("study") == "STUDY"
    assert fake._normalize_retrieve_level("IMAGE") == "INSTANCE"
    assert fake._normalize_retrieve_level("INSTANCE") == "INSTANCE"
    assert fake._normalize_retrieve_level("SERIES") == "SERIES"
    assert fake._normalize_retrieve_level("junk") == "SERIES"


def test_wado_study_level_happy() -> None:
    fake = FakeRetrieve()
    study = _study()
    ds = Dataset()
    ds.SOPInstanceUID = "1.2.sop1"
    with (
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.iter_instances",
            return_value=[ds],
        ) as iter_inst,
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.open_session"
        ) as open_sess,
        patch.object(fake, "_wait_pending_instances"),
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        err = fake._retrieve_study_dicomweb("DW", study, "STUDY")
    assert err is None
    iter_inst.assert_called_once()
    fake.anonymizer.anonymize_dataset_ex.assert_called()


def test_wado_early_outs() -> None:
    fake = FakeRetrieve()
    empty = StudyUIDHierarchy(uid="s", ptid="p", series={})
    assert fake._retrieve_study_dicomweb("DW", empty, "STUDY") == "No Series in Study"

    zero = StudyUIDHierarchy(
        uid="s",
        ptid="p",
        series={"a": SeriesUIDHierarchy(uid="a", instance_count=0)},
    )
    assert fake._retrieve_study_dicomweb("DW", zero, "STUDY") == "No Instances in Study"

    study = _study()
    fake.anonymizer.model.get_pending_instance_count.return_value = 0
    assert fake._retrieve_study_dicomweb("DW", study, "SERIES") == "All Instances already imported"


def test_wado_series_skips_complete_and_zero() -> None:
    fake = FakeRetrieve()
    study = StudyUIDHierarchy(
        uid="1.2.study",
        ptid="P1",
        series={
            "zero": SeriesUIDHierarchy(uid="zero", instance_count=0),
            "done": SeriesUIDHierarchy(uid="done", instance_count=2),
            "need": SeriesUIDHierarchy(uid="need", instance_count=2),
        },
    )

    def series_complete(uid, count):
        return uid == "done"

    fake.anonymizer.model.series_complete.side_effect = series_complete
    called_series: list[str | None] = []

    def iter_instances(session, **kwargs):
        called_series.append(kwargs.get("series_uid"))
        return []

    with (
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.iter_instances",
            side_effect=iter_instances,
        ),
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.open_session"
        ) as open_sess,
        patch.object(fake, "_wait_pending_instances"),
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        err = fake._retrieve_study_dicomweb("DW", study, "SERIES")
    assert err is None
    assert called_series == ["need"]


def test_wado_instance_skips_received() -> None:
    fake = FakeRetrieve()
    study = _study()
    fake.anonymizer.model.instance_received.side_effect = lambda uid: uid == "1.2.sop1"
    requested: list[str | None] = []

    def iter_instances(session, **kwargs):
        requested.append(kwargs.get("instance_uid"))
        return []

    with (
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.iter_instances",
            side_effect=iter_instances,
        ),
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.open_session"
        ) as open_sess,
        patch.object(fake, "_wait_pending_instances"),
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        err = fake._retrieve_study_dicomweb("DW", study, "INSTANCE")
    assert err is None
    assert requested == ["1.2.sop2"]


def test_abort_move_during_wado_ingest() -> None:
    fake = FakeRetrieve()
    study = _study()

    def datasets():
        fake._abort_move = True
        yield Dataset()

    with (
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.iter_instances",
            return_value=datasets(),
        ),
        patch(
            "anonymizer.controller.dicom.retrieve_scu.dicomweb_api.open_session"
        ) as open_sess,
    ):
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        err = fake._retrieve_study_dicomweb("DW", study, "STUDY")
    assert err is not None
    assert "aborted" in err.lower()
    assert study.last_error_msg == err


def test_qr_probe_cache_hit_and_fail_to_move() -> None:
    fake = FakeRetrieve(dicomweb=False)
    fake._qr_get_supported["DIMSE"] = True
    assert fake._probe_qr_get_support("DIMSE") is True

    fake2 = FakeRetrieve(dicomweb=False)
    assert fake2._probe_qr_get_support("DIMSE") is False
    assert fake2._qr_get_supported["DIMSE"] is False


def test_manage_move_picks_wado_for_dicomweb() -> None:
    fake = FakeRetrieve(dicomweb=True)
    study = _study()
    req = MoveStudiesRequest(
        scp_name="DW",
        dest_scp_ae="LOCAL",
        level="SERIES",
        studies=[study],
    )
    with patch.object(fake, "_retrieve_study", return_value=None) as retrieve:
        fake._manage_move(req)
    assert fake._last_retrieve_modality == "WADO"
    retrieve.assert_called_once()
    args = retrieve.call_args[0]
    assert args[4] == "WADO"
    assert args[3] == "SERIES"


def test_abort_move_clears_executor() -> None:
    fake = FakeRetrieve()
    executor = MagicMock()
    fake._move_executor = executor
    fake._move_futures = [("f", "WADO", _study())]
    fake.abort_move()
    executor.shutdown.assert_called_once()
    assert fake._move_executor is None
    assert fake._move_futures is None
    assert fake._abort_move is False
