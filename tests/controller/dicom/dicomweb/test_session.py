"""Unit tests for DICOMweb session open/probe (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import requests

from anonymizer.controller.dicom.dicomweb import session
from anonymizer.model.project import DICOMNode, NetworkTimeouts


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


def test_open_session_without_username_skips_auth() -> None:
    with session.open_session(_node(username=""), _timeouts()) as sess:
        assert sess.http.auth is None
        assert sess.root == "http://127.0.0.1:8042/dicom-web"


def test_url_edge_cases() -> None:
    http = MagicMock()
    sess = session.DicomWebSession(
        node=_node(),
        root="http://h/dicom-web/",
        http=http,
        timeout=(5.0, 60.0),
    )
    assert sess.url() == "http://h/dicom-web"
    assert sess.url("") == "http://h/dicom-web"
    assert sess.url("/studies/", "1.2.3/") == "http://h/dicom-web/studies/1.2.3"


def _probe_with_status(code: int) -> tuple[bool, str]:
    mock_resp = MagicMock()
    mock_resp.status_code = code
    http = MagicMock()
    http.get.return_value = mock_resp
    fake_sess = session.DicomWebSession(
        node=_node(), root="http://h/dicom-web", http=http, timeout=(5.0, 60.0)
    )
    with patch.object(session, "open_session", return_value=fake_sess):
        # open_session used as context manager
        fake_sess.__enter__ = MagicMock(return_value=fake_sess)  # type: ignore[method-assign]
        fake_sess.__exit__ = MagicMock(return_value=False)  # type: ignore[method-assign]
        return session.probe_connection(_node(), _timeouts())


def test_probe_connection_204_success() -> None:
    ok, msg = _probe_with_status(204)
    assert ok is True
    assert "successful" in msg.lower() or "DICOMweb" in msg


def test_probe_connection_403_auth_fail() -> None:
    ok, msg = _probe_with_status(403)
    assert ok is False
    assert "auth" in msg.lower() or "Authentication" in msg


def test_probe_connection_5xx() -> None:
    ok, msg = _probe_with_status(503)
    assert ok is False
    assert "503" in msg or "HTTP" in msg


def test_probe_connection_timeout() -> None:
    with patch.object(session, "open_session") as open_sess:
        cm = MagicMock()
        cm.__enter__.side_effect = requests.Timeout()
        cm.__exit__.return_value = False
        open_sess.return_value = cm
        ok, msg = session.probe_connection(_node(), _timeouts())
    assert ok is False
    assert "timed out" in msg.lower() or "Timeout" in msg


def test_probe_connection_request_exception() -> None:
    with patch.object(session, "open_session") as open_sess:
        cm = MagicMock()
        cm.__enter__.side_effect = requests.RequestException("boom")
        cm.__exit__.return_value = False
        open_sess.return_value = cm
        ok, msg = session.probe_connection(_node(), _timeouts())
    assert ok is False
    assert "boom" in msg


def test_probe_not_dicomweb() -> None:
    ok, msg = session.probe_connection(_node(dicomweb=False), _timeouts())
    assert ok is False
    assert "DICOMweb" in msg
