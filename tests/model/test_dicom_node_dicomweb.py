"""DICOMNode DICOMweb fields and ProjectModel version."""

from __future__ import annotations

from anonymizer.model.project import DICOMNode, ProjectModel


def test_dicomweb_root_composition():
    node = DICOMNode(
        "10.0.0.1",
        104,
        "PACS",
        False,
        dicomweb=True,
        http_port=8042,
        http_path="/dicom-web",
        use_https=False,
    )
    assert node.dicomweb_root() == "http://10.0.0.1:8042/dicom-web"


def test_dicomweb_root_https_and_path_normalization():
    node = DICOMNode(
        "pacs.example",
        11112,
        "AE",
        False,
        dicomweb=True,
        http_port=443,
        http_path="wado/",
        use_https=True,
    )
    assert node.dicomweb_root() == "https://pacs.example:443/wado"


def test_dicomweb_repr_hides_password_in_project_model():
    model = ProjectModel()
    model.remote_scps["QUERY"] = DICOMNode(
        "127.0.0.1",
        4242,
        "ORTHANC",
        False,
        dicomweb=True,
        username="u",
        password="secret",
    )
    text = repr(model)
    assert "secret" not in text
    assert "*****" in text or "*" in text


def test_dicom_node_json_roundtrip_defaults():
    node = DICOMNode("1.2.3.4", 104, "AE", False)
    model = ProjectModel()
    model.remote_scps["QUERY"] = node
    raw = model.to_json()
    loaded = ProjectModel.from_json(raw)
    q = loaded.remote_scps["QUERY"]
    assert q.dicomweb is False
    assert q.http_port == 8042
    assert q.http_path == "/dicom-web"
    assert q.username == ""
    assert q.password == ""


def test_model_version_is_current():
    assert ProjectModel.MODEL_VERSION == 11
    assert ProjectModel().version == ProjectModel.MODEL_VERSION
