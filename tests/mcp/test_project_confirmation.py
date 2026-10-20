"""E2E contract for server-owned project-configuration confirmation."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from anonymizer.controller.project import ProjectController
from anonymizer.mcp import api as mcp_tools
from anonymizer.mcp.api.schemas import (
    ConfigureRemoteArgs,
    CreateProjectArgs,
    LocalDicomNodeArgs,
    NetworkTimeoutsArgs,
    UpdateProjectSettingsArgs,
)
from anonymizer.mcp.session import SESSION
from anonymizer.model.project import DICOMNode, NetworkTimeouts, ProjectModel
from anonymizer.utils.translate import set_language_code
from tests.mcp.project_create import confirm_create

DAVIDSON_DCM = next(
    (
        Path(__file__).resolve().parent.parent
        / "controller"
        / "assets"
        / "test_dcm_files"
        / "davidson_cxr"
    ).glob("*.dcm")
)


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_language_code("en_US")
    monkeypatch.setattr(
        ProjectModel,
        "base_dir",
        staticmethod(lambda: tmp_path / "RSNA Anonymizer"),
    )
    SESSION.close()
    yield
    SESSION.close()


def test_configuration_schemas_are_generated_from_core_dataclasses():
    project_fields = {field.name for field in dataclasses.fields(ProjectModel)}
    expected_create = {
        "project_name",
        "storage_dir",
        "site_id",
        "uid_root",
        "language_code",
        "modalities",
        "transfer_syntaxes",
        "scp",
        "network_timeouts",
        "anonymization_policy",
    }
    assert expected_create <= project_fields
    assert set(CreateProjectArgs.model_fields) == expected_create | {
        "overwrite",
        "confirm",
        "revision",
    }
    assert set(UpdateProjectSettingsArgs.model_fields) == {
        "modalities",
        "transfer_syntaxes",
        "scp",
        "network_timeouts",
        "anonymization_policy",
    }
    assert set(LocalDicomNodeArgs.model_fields) == {
        field.name for field in dataclasses.fields(DICOMNode)[:3]
    }
    assert set(NetworkTimeoutsArgs.model_fields) == {
        field.name for field in dataclasses.fields(NetworkTimeouts)
    }
    dicom_fields = {field.name for field in dataclasses.fields(DICOMNode)}
    assert set(ConfigureRemoteArgs.model_fields) == (dicom_fields - {"local"}) | {"role"}
    assert "import_plan" not in CreateProjectArgs.model_fields
    assert "import_plan" not in UpdateProjectSettingsArgs.model_fields


def test_prepare_returns_supplied_values_combined_with_defaults(tmp_path: Path):
    prepared = mcp_tools.create_project(
        project_name="ConfirmMe",
        anonymization_policy="clinical",
        modalities=["CT", "MR"],
    )

    assert prepared["ok"] is True
    assert prepared["status"] == "confirmation_required"
    assert prepared["created"] is False
    assert prepared["revision"] == 1
    assert SESSION.is_open is False
    assert SESSION.pending_project is not None
    assert isinstance(SESSION.pending_project, ProjectModel)

    storage = tmp_path / "RSNA Anonymizer" / "ConfirmMe"
    assert not (storage / ProjectController.PROJECT_MODEL_FILENAME_JSON).exists()

    configuration = prepared["configuration"]
    assert configuration["project_name"] == "ConfirmMe"
    assert configuration["anonymization_policy"] == "clinical"
    # Clinical policy installs SR/PDF at creation, so the preview shows them.
    assert configuration["modalities"] == ["CT", "MR", "SR", "PDF"]
    assert configuration["language_code"] == ProjectModel.default_language_code()
    assert configuration["uid_root"] == ProjectModel.default_uid_root()
    assert configuration["scp"]["aet"] == ProjectModel.default_local_server().aet
    assert set(prepared["supplied_by_user"]) == {
        "project_name",
        "anonymization_policy",
        "modalities",
    }
    assert "language_code" in prepared["using_defaults"]
    assert "network_timeouts" in prepared["using_defaults"]


def test_revision_updates_pending_model_and_stale_revision_cannot_create(tmp_path: Path):
    first = mcp_tools.create_project(
        project_name="ReviseMe",
        modalities=["CT"],
    )
    revised = mcp_tools.create_project(
        project_name="ReviseMe",
        modalities=["CT", "US"],
        language_code="fr",
    )

    assert revised["revision"] == first["revision"] + 1
    assert revised["configuration"]["modalities"] == ["CT", "US"]
    assert revised["configuration"]["language_code"] == "fr"
    assert revised["configuration"]["site_id"] == first["configuration"]["site_id"]
    assert set(revised["supplied_by_user"]) == {
        "project_name",
        "modalities",
        "language_code",
    }

    stale = mcp_tools.create_project(
        project_name="ReviseMe",
        confirm=True,
        revision=first["revision"],
    )
    assert stale["status"] == "confirmation_required"
    assert stale["created"] is False
    assert SESSION.is_open is False
    storage = tmp_path / "RSNA Anonymizer" / "ReviseMe"
    assert not (storage / ProjectController.PROJECT_MODEL_FILENAME_JSON).exists()

    created = mcp_tools.create_project(
        project_name="ReviseMe",
        confirm=True,
        revision=revised["revision"],
    )
    assert created["status"] == "created"
    assert created["created"] is True
    assert SESSION.pending_project is None
    assert SESSION.controller.model.modalities == ["CT", "US"]
    assert SESSION.controller.model.language_code == "fr"
    assert (storage / ProjectController.PROJECT_MODEL_FILENAME_JSON).is_file()


def test_confirm_true_first_call_only_prepares_configuration():
    result = mcp_tools.create_project(
        project_name="NoSkip",
        confirm=True,
        revision=1,
    )

    assert result["ok"] is True
    assert result["status"] == "confirmation_required"
    assert result["created"] is False
    assert SESSION.is_open is False
    assert SESSION.pending_project is not None


def test_confirmed_project_can_update_settings_and_import_without_a_plan():
    created = confirm_create(
        mcp_tools.create_project,
        project_name="WorkAfterCreate",
        modalities=["CR"],
    )
    assert created["status"] == "created"

    updated = mcp_tools.update_project_settings(
        modalities=["CR", "DX"],
    )
    assert updated["ok"] is True
    assert updated["status"] == "updated"
    assert updated["project"]["modalities"] == ["CR", "DX"]

    imported = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert imported["ok"] is True
    assert imported["succeeded"] == 1


def test_opening_existing_project_discards_pending_configuration():
    created = confirm_create(mcp_tools.create_project, project_name="Existing")
    assert created["ok"] is True
    SESSION.close()

    assert mcp_tools.create_project(project_name="Pending")["status"] == (
        "confirmation_required"
    )
    assert SESSION.pending_project is not None

    opened = mcp_tools.project_open(project_name="Existing")
    assert opened["ok"] is True
    assert SESSION.pending_project is None
