"""Unit tests for controller.dicom.dicomweb (mocked HTTP)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset, dcmwrite
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.dicom.dicomweb import qido, session, stow, wado
from anonymizer.controller.dicom.dicomweb.qido import qido_json_to_dataset
from anonymizer.model.project import DICOMNode, DICOMRuntimeError, NetworkTimeouts


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


def _minimal_dcm_bytes(*, sop_instance_uid: str | None = None) -> bytes:
    ds = Dataset()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = sop_instance_uid or generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = "P1"
    ds.Modality = "CT"
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    buf = BytesIO()
    dcmwrite(buf, ds, enforce_file_format=True)
    return buf.getvalue()


def test_open_session_requires_dicomweb():
    with pytest.raises(ValueError, match="DICOMweb"):
        session.open_session(_node(dicomweb=False), _timeouts())


def test_open_session_sets_basic_auth_and_root():
    with session.open_session(_node(), _timeouts()) as sess:
        assert sess.root == "http://127.0.0.1:8042/dicom-web"
        assert sess.http.auth is not None
        assert sess.url("studies") == "http://127.0.0.1:8042/dicom-web/studies"


def test_qido_json_to_dataset_maps_tags():
    item = {
        "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
        "00100010": {"vr": "PN", "Value": [{"Alphabetic": "DOE^JOHN"}]},
        "00080060": {"vr": "CS", "Value": ["CT", "SR"]},
    }
    ds = qido_json_to_dataset(item)
    assert ds.StudyInstanceUID == "1.2.3"
    assert str(ds.PatientName) == "DOE^JOHN"
    assert list(ds.Modality) == ["CT", "SR"] or ds.Modality == ["CT", "SR"]


def test_find_studies_builds_params_and_maps():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
            "00100020": {"vr": "LO", "Value": ["PID1"]},
            "00080050": {"vr": "SH", "Value": ["ACC1"]},
            "00201206": {"vr": "IS", "Value": ["2"]},
            "00201208": {"vr": "IS", "Value": ["10"]},
            "00080061": {"vr": "CS", "Value": ["CT"]},
        }
    ]
    http = MagicMock()
    http.get.return_value = mock_resp
    sess = session.DicomWebSession(
        node=_node(), root="http://h/dicom-web", http=http, timeout=(5.0, 60.0)
    )
    results = qido.find_studies(sess, patient_id="PID1", accession="ACC1")
    assert len(results) == 1
    assert results[0].StudyInstanceUID == "1.2.3"
    assert results[0].PatientID == "PID1"
    http.get.assert_called_once()
    _, kwargs = http.get.call_args
    params = dict(kwargs["params"]) if isinstance(kwargs["params"], dict) else {
        k: v for k, v in kwargs["params"]
    }
    assert params.get("PatientID") == "PID1" or ("PatientID", "PID1") in kwargs["params"]


def test_find_studies_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"
    http = MagicMock()
    http.get.return_value = mock_resp
    sess = session.DicomWebSession(
        node=_node(), root="http://h/dicom-web", http=http, timeout=(5.0, 60.0)
    )
    with pytest.raises(DICOMRuntimeError, match="401"):
        qido.find_studies(sess)


def test_wado_iter_single_part():
    body = _minimal_dcm_bytes()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/dicom"}
    mock_resp.content = body
    http = MagicMock()
    http.get.return_value = mock_resp
    sess = session.DicomWebSession(
        node=_node(), root="http://h/dicom-web", http=http, timeout=(5.0, 60.0)
    )
    datasets = list(wado.iter_instances(sess, study_uid="1.2.3"))
    assert len(datasets) == 1
    assert datasets[0].SOPInstanceUID


def _multipart_related_dicom(parts: list[bytes], *, boundary: str = "Boundary_UnitTest") -> tuple[str, bytes]:
    """Build a WADO-RS-style multipart/related body with application/dicom parts."""
    chunks: list[bytes] = []
    for data in parts:
        chunks.append(f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    content_type = f'multipart/related; type="application/dicom"; boundary="{boundary}"'
    return content_type, b"".join(chunks)


def test_wado_parse_multipart_dicom_two_instances():
    sop_a = generate_uid()
    sop_b = generate_uid()
    content_type, body = _multipart_related_dicom(
        [_minimal_dcm_bytes(sop_instance_uid=sop_a), _minimal_dcm_bytes(sop_instance_uid=sop_b)]
    )
    datasets = wado._parse_multipart_dicom(content_type, body)
    assert len(datasets) == 2
    assert {ds.SOPInstanceUID for ds in datasets} == {sop_a, sop_b}


def test_wado_iter_multipart_related():
    sop_a = generate_uid()
    sop_b = generate_uid()
    content_type, body = _multipart_related_dicom(
        [_minimal_dcm_bytes(sop_instance_uid=sop_a), _minimal_dcm_bytes(sop_instance_uid=sop_b)]
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": content_type}
    mock_resp.content = body
    http = MagicMock()
    http.get.return_value = mock_resp
    sess = session.DicomWebSession(
        node=_node(), root="http://h/dicom-web", http=http, timeout=(5.0, 60.0)
    )
    datasets = list(wado.iter_instances(sess, study_uid="1.2.3"))
    assert len(datasets) == 2
    assert {ds.SOPInstanceUID for ds in datasets} == {sop_a, sop_b}
    _, kwargs = http.get.call_args
    assert "multipart/related" in kwargs["headers"]["Accept"]


def test_stow_store_files(tmp_path):
    path = tmp_path / "a.dcm"
    path.write_bytes(_minimal_dcm_bytes())
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    http = MagicMock()
    http.post.return_value = mock_resp
    sess = session.DicomWebSession(
        node=_node(), root="http://h/dicom-web", http=http, timeout=(5.0, 60.0)
    )
    n = stow.store_files(sess, [str(path)])
    assert n == 1
    http.post.assert_called_once()
    _, kwargs = http.post.call_args
    assert "multipart/related" in kwargs["headers"]["Content-Type"]


def test_find_mixin_dicomweb_branch():
    from anonymizer.controller.dicom.find_scu import FindMixin

    class Fake(FindMixin):
        def __init__(self):
            self.model = MagicMock()
            self.model.network_timeouts = _timeouts()
            self.model.remote_scps = {"QUERY": _node()}
            self._abort_query = False
            self._required_attributes_study_query = [
                "StudyInstanceUID",
                "ModalitiesInStudy",
                "NumberOfStudyRelatedSeries",
                "NumberOfStudyRelatedInstances",
            ]

        def _resolve_remote(self, scp):
            return self.model.remote_scps[scp]

        def _missing_attributes(self, required, ds):
            return [a for a in required if not hasattr(ds, a)]

        def _strip_query_result_fields(self, ds):
            return

    fake = Fake()
    study = Dataset()
    study.StudyInstanceUID = "1.2.3"
    study.ModalitiesInStudy = "CT"
    study.NumberOfStudyRelatedSeries = 1
    study.NumberOfStudyRelatedInstances = 2

    with patch(
        "anonymizer.controller.dicom.find_scu.dicomweb_api.find_studies",
        return_value=[study],
    ), patch(
        "anonymizer.controller.dicom.find_scu.dicomweb_api.open_session"
    ) as open_sess:
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        results = fake.find_studies("QUERY", "", "PID", "", "", "")
    assert len(results) == 1
    assert results[0].StudyInstanceUID == "1.2.3"


def test_store_mixin_dicomweb_branch(tmp_path):
    from anonymizer.controller.dicom.store_scu import StoreMixin

    path = tmp_path / "b.dcm"
    path.write_bytes(_minimal_dcm_bytes())

    class Fake(StoreMixin):
        def __init__(self):
            self.model = MagicMock()
            self.model.network_timeouts = _timeouts()
            self.model.remote_scps = {"EXPORT": _node()}

        def _resolve_remote(self, scp):
            return self.model.remote_scps[scp]

    fake = Fake()
    with patch(
        "anonymizer.controller.dicom.store_scu.dicomweb_api.store_files", return_value=1
    ) as store_files, patch(
        "anonymizer.controller.dicom.store_scu.dicomweb_api.open_session"
    ) as open_sess:
        open_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
        open_sess.return_value.__exit__ = MagicMock(return_value=False)
        n = fake.send([str(path)], "EXPORT")
    assert n == 1
    store_files.assert_called_once()
