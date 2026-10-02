"""Tests for Query/Export DICOM node form mapping and DICOMweb probe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.dicom.dicomweb.session import probe_connection
from anonymizer.model.project import DICOMNode, NetworkTimeouts
from anonymizer.view.settings.dicom_node_dialog import (
    RemoteNodeFormValues,
    apply_https_port_default,
    dicomweb_fresh_defaults,
    remote_node_from_form,
    validate_remote_form,
)


def _timeouts() -> NetworkTimeouts:
    return NetworkTimeouts(tcp_connection=5.0, acse=5.0, dimse=5.0, network=10.0)


def test_remote_node_from_form_scp_clears_web_fields():
    node = remote_node_from_form(
        RemoteNodeFormValues(
            ip="10.0.0.1",
            dicomweb=False,
            port=4242,
            aet="ORTHANC",
            dimse_port=4242,
            http_path="/dicom-web",
            use_https=True,
            username="u",
            password="p",
        )
    )
    assert node.dicomweb is False
    assert node.port == 4242
    assert node.aet == "ORTHANC"
    assert node.http_port == 8042
    assert node.use_https is False
    assert node.username == ""
    assert node.password == ""


def test_remote_node_from_form_dicomweb_uses_http_port():
    node = remote_node_from_form(
        RemoteNodeFormValues(
            ip="10.0.0.1",
            dicomweb=True,
            port=443,
            aet="",
            dimse_port=4242,
            http_path="dicom-web",
            use_https=True,
            username="u",
            password="secret",
        )
    )
    assert node.dicomweb is True
    assert node.port == 4242  # DIMSE port preserved
    assert node.http_port == 443
    assert node.http_path == "/dicom-web"
    assert node.use_https is True
    assert node.aet == "WEB"
    assert node.username == "u"
    assert node.password == "secret"
    assert node.dicomweb_root() == "https://10.0.0.1:443/dicom-web"


def test_validate_remote_form_requires_paired_creds():
    err = validate_remote_form(
        RemoteNodeFormValues(
            ip="1.2.3.4",
            dicomweb=True,
            port=443,
            aet="WEB",
            dimse_port=104,
            http_path="/dicom-web",
            use_https=True,
            username="only-user",
            password="",
        )
    )
    assert err is not None
    assert "password" in err.lower() or "Username" in err


def test_validate_remote_form_scp_requires_aet():
    err = validate_remote_form(
        RemoteNodeFormValues(
            ip="1.2.3.4",
            dicomweb=False,
            port=104,
            aet="  ",
            dimse_port=104,
            http_path="/dicom-web",
            use_https=False,
            username="",
            password="",
        )
    )
    assert err is not None


def test_https_port_defaults():
    assert apply_https_port_default(True, 8042) == 443
    assert apply_https_port_default(True, 80) == 443
    assert apply_https_port_default(True, 8443) == 8443
    assert apply_https_port_default(False, 443) == 80
    assert apply_https_port_default(False, 8443) == 8443


def test_dicomweb_fresh_defaults_https_first():
    port, https, path = dicomweb_fresh_defaults(previous_http_port=8042)
    assert port == 443
    assert https is True
    assert path == "/dicom-web"


def test_probe_connection_success():
    node = DICOMNode("127.0.0.1", 104, "WEB", False, dicomweb=True, http_port=8042)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "[]"
    mock_http = MagicMock()
    mock_http.get.return_value = mock_resp
    mock_session = MagicMock()
    mock_session.http = mock_http
    mock_session.timeout = (5.0, 10.0)
    mock_session.url.return_value = "http://127.0.0.1:8042/dicom-web/studies"
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None
    with patch(
        "anonymizer.controller.dicom.dicomweb.session.open_session",
        return_value=mock_session,
    ):
        ok, msg = probe_connection(node, _timeouts())
    assert ok is True
    assert "successful" in msg.lower()
    mock_http.get.assert_called_once()


def test_probe_connection_auth_failure():
    node = DICOMNode(
        "127.0.0.1",
        104,
        "WEB",
        False,
        dicomweb=True,
        http_port=443,
        use_https=True,
        username="u",
        password="bad",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"
    mock_http = MagicMock()
    mock_http.get.return_value = mock_resp
    mock_session = MagicMock()
    mock_session.http = mock_http
    mock_session.timeout = (5.0, 10.0)
    mock_session.url.return_value = "https://127.0.0.1:443/dicom-web/studies"
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None
    with patch(
        "anonymizer.controller.dicom.dicomweb.session.open_session",
        return_value=mock_session,
    ):
        ok, msg = probe_connection(node, _timeouts())
    assert ok is False
    assert "auth" in msg.lower()


def test_probe_connection_rejects_non_web_node():
    node = DICOMNode("127.0.0.1", 104, "AE", False, dicomweb=False)
    ok, msg = probe_connection(node, _timeouts())
    assert ok is False
    assert "DICOMweb" in msg


def test_probe_connection_connection_refused():
    import requests

    node = DICOMNode("127.0.0.1", 104, "WEB", False, dicomweb=True, http_port=8042, use_https=True)
    with patch(
        "anonymizer.controller.dicom.dicomweb.session.open_session",
        side_effect=requests.ConnectionError(
            "HTTPSConnectionPool(host='127.0.0.1', port=8042): Max retries exceeded "
            "(Caused by NewConnectionError(\"[Errno 61] Connection refused\"))"
        ),
    ):
        ok, msg = probe_connection(node, _timeouts())
    assert ok is False
    assert msg == "Connection refused"


def test_probe_connection_timeout():
    import requests

    node = DICOMNode("127.0.0.1", 104, "WEB", False, dicomweb=True, http_port=443, use_https=True)
    with patch(
        "anonymizer.controller.dicom.dicomweb.session.open_session",
        side_effect=requests.Timeout("timed out"),
    ):
        ok, msg = probe_connection(node, _timeouts())
    assert ok is False
    assert msg == "Connection timed out"


def test_connection_status_category():
    from anonymizer.view.settings.dicom_node_dialog import connection_status_category

    assert connection_status_category("Connection error to: AET 'X' on host 1.2.3.4:104") == "Connection error"
    assert "refused" in connection_status_category("[Errno 61] Connection refused").lower()
    assert "auth" in connection_status_category("DICOMweb authentication failed (HTTP 401)").lower()
    assert "timed out" in connection_status_category("Connection timed out").lower()
