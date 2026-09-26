"""Pydantic input models — single source of truth for MCP ``inputSchema``.

Field descriptions and validators are what clients (and LLMs) see via
``tools/list``. Do not duplicate these strings on handler signatures.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from anonymizer.mcp.ops import PacsMoveLevel, RemoteScpRole

# Reject doc placeholders that small models copy from examples.
_PLACEHOLDER_PATH = re.compile(
    r"(?i)(/absolute/path|path/to/|placeholder|your[_-]?path|</|\.\.\.|…)"
)

PATIENT_DESC = (
    'From list_inventory: "all" | "<patient_index>" | "<anon_patient_id>" (e.g. "1"). '
    'Never invent patient_name. "all" is only for batch tools (remove_pixel_phi / harmonize), '
    "not for export_series_preview."
)
STUDY_DESC = (
    'From list_inventory: "all" | "<study_index>" (e.g. "1"). '
    '"all" is only for batch tools, not for export_series_preview.'
)
SERIES_DESC = (
    'From list_inventory: "all" | "<series_index>" | modality code | description substring '
    '(e.g. "1", "cxr"). "all" is only for batch tools, not for export_series_preview.'
)
EXPORT_PATIENT_DESC = (
    'Exactly one patient from list_inventory: "<patient_index>" or "<anon_patient_id>" '
    '(e.g. "1", "2", "994681-000002"). Never "all". Call list_inventory first if unknown.'
)
EXPORT_STUDY_DESC = (
    'Optional study_index from list_inventory for that patient (e.g. "1"). Never "all".'
)
EXPORT_SERIES_DESC = (
    'Exactly one series: series_index within the patient/study, or list_inventory row_index '
    'when patient is omitted (e.g. series="2" = second inventory row). Never "all".'
)
MODALITIES_DESC = (
    'Allowed ingest modalities. Examples: ["defaults","US"], "defaults and ultrasound", '
    '"CT, MR, US". Omit for project defaults (CR, DX, CT, MR).'
)


def _require_user_absolute_path(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("path is required; use a real absolute path from the user")
    if not Path(text).is_absolute():
        raise ValueError("must be an absolute filesystem path supplied by the user")
    if _PLACEHOLDER_PATH.search(text):
        raise ValueError(
            "refusing placeholder path; ask the user for a real absolute path on this machine"
        )
    return text


class EmptyArgs(BaseModel):
    """Zero-argument tools: call with ``arguments: {}`` only."""

    model_config = ConfigDict(extra="forbid")


class CreateProjectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(
        description=(
            "Project display name exactly as the user stated (required). "
            "Do not invent or rename."
        ),
    )
    storage_dir: str | None = Field(
        default=None,
        description=(
            "Optional absolute directory for the project store, only if the user provided one. "
            "Omit to use the default under ~/Documents/RSNA Anonymizer/<project_name>."
        ),
    )
    overwrite: bool = Field(
        default=False,
        description="Replace an existing project at the same location (only if the user asked).",
    )
    modalities: list[str] | str | None = Field(default=None, description=MODALITIES_DESC)

    @field_validator("storage_dir")
    @classmethod
    def _storage_dir_abs(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        return _require_user_absolute_path(str(v))


class ProjectOpenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str | None = Field(
        default=None,
        description=(
            "Existing project name under the default store when storage_dir is omitted. "
            "Use the name the user gave; do not invent."
        ),
    )
    storage_dir: str | None = Field(
        default=None,
        description=(
            "Absolute project directory (or folder containing ProjectModel.json), "
            "only if the user provided it."
        ),
    )
    modalities: list[str] | str | None = Field(default=None, description=MODALITIES_DESC)

    @field_validator("storage_dir")
    @classmethod
    def _storage_dir_abs(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        return _require_user_absolute_path(str(v))


class ImportDirectoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(
        description=(
            "Absolute path to a DICOM study folder on this machine. "
            "Required from the user — never invent or copy documentation placeholders."
        ),
    )

    @field_validator("directory")
    @classmethod
    def _dir_abs(cls, v: str) -> str:
        return _require_user_absolute_path(v)


class ImportFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(
        description=(
            "Absolute path to one DICOM file on this machine. "
            "Required from the user — never invent or copy documentation placeholders."
        ),
    )

    @field_validator("file_path")
    @classmethod
    def _file_abs(cls, v: str) -> str:
        return _require_user_absolute_path(v)


class ConfigureRemoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ip: str = Field(description="Remote PACS host IP or hostname exactly as the user stated.")
    port: int = Field(description="Remote DICOM port (integer from the user).")
    aet: str = Field(description="Remote AE title exactly as the user stated.")
    role: RemoteScpRole = Field(
        default=RemoteScpRole.QUERY,
        description="Remote SCP role: QUERY (find/move) or EXPORT.",
    )


class PacsFindArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_name: str | None = Field(
        default=None, description="PatientName DICOM query value (omit if unused)."
    )
    patient_id: str | None = Field(
        default=None, description="PatientID DICOM query value (omit if unused)."
    )
    accession: str | None = Field(
        default=None, description="AccessionNumber query value (omit if unused)."
    )
    study_date: str | None = Field(
        default=None, description="StudyDate query value, DICOM DA format (omit if unused)."
    )
    modality: str | None = Field(
        default=None, description="Modality query value such as CR or CT (omit if unused)."
    )


class PacsStudyRef(BaseModel):
    """One study row from ``pacs_find`` for ``pacs_move``."""

    model_config = ConfigDict(extra="forbid")

    study_instance_uid: str = Field(description="StudyInstanceUID from pacs_find results.")
    patient_id: str = Field(description="PatientID from pacs_find results.")


class PacsMoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studies: list[PacsStudyRef] = Field(
        description="Studies chosen from pacs_find results (study_instance_uid + patient_id).",
    )
    level: PacsMoveLevel = Field(
        default=PacsMoveLevel.SERIES,
        description="C-MOVE level: STUDY, SERIES, or INSTANCE.",
    )


class SeriesSelectorsArgs(BaseModel):
    """Shared optional selectors for batch imaging tools (from list_inventory only)."""

    model_config = ConfigDict(extra="forbid")

    patient: str | None = Field(default=None, description=PATIENT_DESC)
    study: str | None = Field(default=None, description=STUDY_DESC)
    series: str | None = Field(default=None, description=SERIES_DESC)


class ExportPreviewArgs(BaseModel):
    """Selectors for ``export_series_preview`` — must identify exactly one series."""

    model_config = ConfigDict(extra="forbid")

    patient: str | None = Field(default=None, description=EXPORT_PATIENT_DESC)
    study: str | None = Field(default=None, description=EXPORT_STUDY_DESC)
    series: str | None = Field(default=None, description=EXPORT_SERIES_DESC)

    @field_validator("patient", "study", "series")
    @classmethod
    def _forbid_all(cls, v: str | None) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        if not text:
            return None
        if text.lower() in {"all", "*"}:
            raise ValueError(
                'Do not use "all". Call list_inventory, then pass one patient_index / '
                "study_index / series_index (or row_index as series) from that table."
            )
        return text


class HarmonizeStudiesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient: str | None = Field(default=None, description=PATIENT_DESC)
    study: str | None = Field(default=None, description=STUDY_DESC)
