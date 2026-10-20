"""Pydantic input models — single source of truth for MCP ``inputSchema``.

Field descriptions and validators are what clients (and LLMs) see via
``tools/list``. Do not duplicate these strings on handler signatures.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Annotated, Any, get_type_hints

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)

from anonymizer.mcp.ops import PacsMoveLevel, RemoteScpRole
from anonymizer.model.project import DICOMNode, NetworkTimeouts, ProjectModel
from anonymizer.model.settings_validate import (
    ACSE_TIMEOUT_MAX,
    ACSE_TIMEOUT_MIN,
    AET_CHARSET,
    AET_MAX_CHARS,
    AET_MIN_CHARS,
    DIMSE_TIMEOUT_MAX,
    DIMSE_TIMEOUT_MIN,
    HTTP_PATH_CHARSET,
    HTTP_PATH_MAX_CHARS,
    HTTP_PATH_MIN_CHARS,
    IP_CHARSET,
    IP_MAX_CHARS,
    IP_MIN_CHARS,
    IP_PORT_MAX,
    IP_PORT_MIN,
    NETWORK_TIMEOUT_MAX,
    NETWORK_TIMEOUT_MIN,
    PROJECT_NAME_CHARSET,
    PROJECT_NAME_MAX_CHARS,
    PROJECT_NAME_MIN_CHARS,
    SITE_ID_CHARSET,
    SITE_ID_MAX_CHARS,
    SITE_ID_MIN_CHARS,
    TCP_TIMEOUT_MAX,
    TCP_TIMEOUT_MIN,
    UID_ROOT_CHARSET,
    UID_ROOT_MAX_CHARS,
    UID_ROOT_MIN_CHARS,
)
from anonymizer.utils.translate import language_to_code

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
_DEFAULT_SCP = ProjectModel.default_local_server()
_DEFAULT_TIMEOUTS = ProjectModel.default_timeouts()
_LANGUAGE_CODES = " | ".join(sorted(language_to_code.values()))
_MODALITY_CODES = ", ".join(ProjectModel.default_modalities())

MODALITIES_DESC = (
    f"Allowed ingest modalities as DICOM codes, e.g. ['CT', 'MR', 'US']. "
    f"Omit for project defaults ({_MODALITY_CODES})."
)
SITE_ID_DESC = (
    f"Optional site id override at create only ({SITE_ID_MIN_CHARS}–{SITE_ID_MAX_CHARS} "
    "chars; digits, hyphen, period). Omit to auto-generate. Locked after create."
)
UID_ROOT_DESC = (
    f"Optional DICOM UID root at create only ({UID_ROOT_MIN_CHARS}–{UID_ROOT_MAX_CHARS} "
    "chars; digits and period). Omit for the factory default. Locked after create. "
    "Do not invent arbitrary roots."
)
LANGUAGE_DESC = (
    f"UI/project language code: {_LANGUAGE_CODES}. Default en_US. "
    "Chosen once at project creation (like the desktop welcome screen); "
    "it cannot be changed afterwards."
)
SCP_DESC = (
    f"Optional local DICOM SCP (ip, port, aet). Port {IP_PORT_MIN}–{IP_PORT_MAX}; "
    f"AET {AET_MIN_CHARS}–{AET_MAX_CHARS} chars. Mirrored to local SCU. Omit for "
    f"factory defaults ({_DEFAULT_SCP.ip}:{_DEFAULT_SCP.port} / {_DEFAULT_SCP.aet})."
)
TIMEOUTS_DESC = (
    "Optional network timeouts in seconds: "
    f"tcp_connection {TCP_TIMEOUT_MIN}–{TCP_TIMEOUT_MAX}, "
    f"acse {ACSE_TIMEOUT_MIN}–{ACSE_TIMEOUT_MAX}, dimse {DIMSE_TIMEOUT_MIN}–{DIMSE_TIMEOUT_MAX}, "
    f"network {NETWORK_TIMEOUT_MIN}–{NETWORK_TIMEOUT_MAX}. Omit for defaults "
    f"({_DEFAULT_TIMEOUTS.tcp_connection:g}, {_DEFAULT_TIMEOUTS.acse:g}, "
    f"{_DEFAULT_TIMEOUTS.dimse:g}, {_DEFAULT_TIMEOUTS.network:g})."
)
TRANSFER_SYNTAXES_DESC = (
    "Optional list of transfer-syntax UIDs from the project default set. "
    "Omit to keep factory defaults."
)
POLICY_DESC = (
    "Anonymization policy: strict (default, image-focused) or clinical "
    "(keeps more report/clinical tags; enables SR/PDF). "
    "On an existing project, switching policy replaces the packaged anonymizer script."
)
# Shown when configure_remote rejects invented keys (single source for retry hints).
CONFIGURE_REMOTE_EXTRA_HINT = (
    "configure_remote allows only: ip, port, aet, role, dicomweb, http_port, http_path, "
    "use_https, username, password. "
    "Use ip (not host/hostname/address), aet (not aetitle), dicomweb bool (not protocol), "
    "http_path (not path), role QUERY|EXPORT (not query_type)."
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


_MODEL_TYPES: dict[type[Any], dict[str, Any]] = {
    ProjectModel: get_type_hints(ProjectModel),
    DICOMNode: get_type_hints(DICOMNode),
    NetworkTimeouts: get_type_hints(NetworkTimeouts),
}
_MODEL_FIELDS: dict[type[Any], dict[str, dataclasses.Field[Any]]] = {
    source: {field.name: field for field in dataclasses.fields(source)}
    for source in _MODEL_TYPES
}

_FIELD_DESCRIPTIONS: dict[str, str] = {
    "project_name": (
        "Project display name exactly as the user stated (required; "
        f"{PROJECT_NAME_MIN_CHARS}–{PROJECT_NAME_MAX_CHARS} chars; letters, digits, "
        "space, hyphen, period). Do not invent or rename."
    ),
    "storage_dir": (
        "Optional absolute directory for the project store, only if the user provided one. "
        "Omit to use the default under ~/Documents/RSNA Anonymizer/<project_name>. "
        "Locked after create."
    ),
    "site_id": SITE_ID_DESC,
    "uid_root": UID_ROOT_DESC,
    "language_code": LANGUAGE_DESC,
    "modalities": MODALITIES_DESC,
    "transfer_syntaxes": TRANSFER_SYNTAXES_DESC,
    "scp": SCP_DESC,
    "network_timeouts": TIMEOUTS_DESC,
    "anonymization_policy": POLICY_DESC,
    "ip": (
        f"IPv4 address ({IP_MIN_CHARS}–{IP_MAX_CHARS} chars, digits and dots). "
        "Omit to keep current/default."
    ),
    "port": f"DICOM port {IP_PORT_MIN}–{IP_PORT_MAX}. Omit to keep current/default.",
    "aet": (
        f"AE title {AET_MIN_CHARS}–{AET_MAX_CHARS} chars. "
        "Omit to keep current/default."
    ),
    "tcp_connection": (
        f"TCP connect timeout {TCP_TIMEOUT_MIN}–{TCP_TIMEOUT_MAX} s. "
        "Omit to keep current/default."
    ),
    "acse": f"ACSE timeout {ACSE_TIMEOUT_MIN}–{ACSE_TIMEOUT_MAX} s. Omit to keep current/default.",
    "dimse": (
        f"DIMSE timeout {DIMSE_TIMEOUT_MIN}–{DIMSE_TIMEOUT_MAX} s. "
        "Omit to keep current/default."
    ),
    "network": (
        f"Idle network timeout {NETWORK_TIMEOUT_MIN}–{NETWORK_TIMEOUT_MAX} s. "
        "Omit to keep current/default."
    ),
    "dicomweb": (
        "Boolean only — never invent a 'protocol' string key. true when the user chose "
        "DICOMweb (or gave HTTP details); false = classic DIMSE (C-FIND/C-MOVE)."
    ),
    "http_port": (
        f"DICOMweb HTTP port {IP_PORT_MIN}–{IP_PORT_MAX} when dicomweb=true "
        "(default 8042). Field name is http_port — never invent host or protocol."
    ),
    "http_path": (
        f"DICOMweb path prefix {HTTP_PATH_MIN_CHARS}–{HTTP_PATH_MAX_CHARS} chars when "
        "dicomweb=true, e.g. /dicom-web. Field name is http_path — never invent a bare 'path' key."
    ),
    "use_https": "Use HTTPS for DICOMweb when dicomweb=true.",
    "username": "Optional DICOMweb Basic Auth username.",
    "password": "Optional DICOMweb Basic Auth password.",
}

def _charset_pattern(charset: str) -> str:
    """
    Build a JSON Schema pattern from a ``settings_validate`` charset.

    The core model validators in ``settings_validate`` own the allowed
    characters for each settings field; deriving the schema pattern from
    those charsets keeps ``tools/list`` in lockstep with the validation the
    server applies, instead of maintaining a parallel hand-written regex.

    Args:
        charset: Allowed characters, as declared in ``settings_validate``.

    Returns:
        Anchored character-class pattern accepting one or more charset chars.
    """
    return "^[" + "".join(re.escape(char) for char in charset) + "]+$"


# Every limit and charset below comes from anonymizer.model.settings_validate
# (the same constants the core validators enforce) — never re-declare values.
_FIELD_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "project_name": {
        "min_length": PROJECT_NAME_MIN_CHARS,
        "max_length": PROJECT_NAME_MAX_CHARS,
        "pattern": _charset_pattern(PROJECT_NAME_CHARSET),
    },
    "site_id": {
        "min_length": SITE_ID_MIN_CHARS,
        "max_length": SITE_ID_MAX_CHARS,
        "pattern": _charset_pattern(SITE_ID_CHARSET),
    },
    "uid_root": {
        "min_length": UID_ROOT_MIN_CHARS,
        "max_length": UID_ROOT_MAX_CHARS,
        "pattern": _charset_pattern(UID_ROOT_CHARSET),
    },
    "ip": {
        "min_length": IP_MIN_CHARS,
        "max_length": IP_MAX_CHARS,
        "pattern": _charset_pattern(IP_CHARSET),
    },
    "port": {"ge": IP_PORT_MIN, "le": IP_PORT_MAX},
    "http_port": {"ge": IP_PORT_MIN, "le": IP_PORT_MAX},
    "aet": {
        "min_length": AET_MIN_CHARS,
        "max_length": AET_MAX_CHARS,
        "pattern": _charset_pattern(AET_CHARSET),
    },
    "http_path": {
        "min_length": HTTP_PATH_MIN_CHARS,
        "max_length": HTTP_PATH_MAX_CHARS,
        "pattern": _charset_pattern(HTTP_PATH_CHARSET),
    },
    "tcp_connection": {"ge": TCP_TIMEOUT_MIN, "le": TCP_TIMEOUT_MAX},
    "acse": {"ge": ACSE_TIMEOUT_MIN, "le": ACSE_TIMEOUT_MAX},
    "dimse": {"ge": DIMSE_TIMEOUT_MIN, "le": DIMSE_TIMEOUT_MAX},
    "network": {"ge": NETWORK_TIMEOUT_MIN, "le": NETWORK_TIMEOUT_MAX},
}


def _model_annotation(source: type[Any], name: str) -> Any:
    """
    Return the dataclass annotation for one core model field.

    Args:
        source: Core dataclass type.
        name: Field name that must exist on ``source``.

    Returns:
        The resolved Python annotation.

    Raises:
        ValueError: If the MCP projection names a field the core model lacks.
    """
    try:
        return _MODEL_TYPES[source][name]
    except KeyError as exc:
        raise ValueError(f"{source.__name__} has no field {name!r} for MCP schema") from exc


def _generated_field(
    source: type[Any],
    name: str,
    *,
    required: bool = False,
    annotation: Any = None,
    description: str | None = None,
    default: Any = None,
) -> tuple[Any, Any]:
    """
    Build one Pydantic field definition from a core dataclass field.

    Args:
        source: Core dataclass that owns the field.
        name: Field name on ``source``.
        required: Whether the tool projection requires the field.
        annotation: Optional transport annotation replacing the dataclass type.
        description: Optional LLM-facing field description.
        default: Default for an optional field.

    Returns:
        ``(annotation, FieldInfo)`` pair suitable for ``create_model``.
    """
    resolved = annotation if annotation is not None else _model_annotation(source, name)
    if not required:
        resolved = resolved | None
    field_kwargs: dict[str, Any] = {
        "description": description or _FIELD_DESCRIPTIONS.get(name, name)
    }
    field_kwargs.update(_FIELD_CONSTRAINTS.get(name, {}))
    if required:
        return resolved, Field(**field_kwargs)
    return resolved, Field(default=default, **field_kwargs)


def _generated_model(
    name: str,
    definitions: dict[str, tuple[Any, Any]],
    *,
    base: type[BaseModel] | None = None,
) -> type[BaseModel]:
    """
    Create a strict Pydantic model from generated field definitions.

    Args:
        name: Pydantic model name.
        definitions: Mapping of field name to ``(annotation, FieldInfo)``.
        base: Optional base model carrying config/validators.

    Returns:
        The generated Pydantic model type.
    """
    kwargs: dict[str, Any] = {}
    if base is not None:
        kwargs["__base__"] = base
    else:
        kwargs["__config__"] = ConfigDict(extra="forbid")
    return create_model(name, **kwargs, **definitions)  # type: ignore[arg-type]


class _SettingsPatchBase(BaseModel):
    """Base for generated mutable-settings models: at least one real value."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_setting(self) -> "_SettingsPatchBase":
        """
        Reject an update containing no non-null setting.

        Returns:
            This validated model.

        Raises:
            ValueError: If every generated setting is null.
        """
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("Provide at least one mutable project setting")
        return self


def _patch_definitions(
    source: type[Any],
    names: tuple[str, ...],
    *,
    annotations: dict[str, Any] | None = None,
) -> dict[str, tuple[Any, Any]]:
    """
    Generate all-optional field definitions for selected dataclass fields.

    Args:
        source: Core dataclass that owns the fields.
        names: Field names to project.
        annotations: Optional transport annotation overrides by field name.

    Returns:
        Field definitions suitable for ``create_model``.
    """
    overrides = annotations or {}
    return {
        name: _generated_field(
            source,
            name,
            annotation=overrides.get(name),
        )
        for name in names
    }


_LOCAL_DICOM_NODE_FIELDS = ("ip", "port", "aet")
LocalDicomNodeArgs = _generated_model(
    "LocalDicomNodeArgs",
    _patch_definitions(DICOMNode, _LOCAL_DICOM_NODE_FIELDS),
)
LocalDicomNodeArgs.__doc__ = "Local SCP (and mirrored SCU) fields generated from DICOMNode."

_NETWORK_TIMEOUT_FIELDS = tuple(_MODEL_FIELDS[NetworkTimeouts])
NetworkTimeoutsArgs = _generated_model(
    "NetworkTimeoutsArgs",
    _patch_definitions(NetworkTimeouts, _NETWORK_TIMEOUT_FIELDS),
)
NetworkTimeoutsArgs.__doc__ = "Network timeout fields generated from NetworkTimeouts."

_PROJECT_CREATE_FIELDS = (
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
)
_PROJECT_MUTABLE_FIELDS = (
    "modalities",
    "transfer_syntaxes",
    "scp",
    "network_timeouts",
    "anonymization_policy",
)
_PROJECT_ANNOTATIONS: dict[str, Any] = {
    "storage_dir": Annotated[str, AfterValidator(_require_user_absolute_path)],
    "scp": LocalDicomNodeArgs,
    "network_timeouts": NetworkTimeoutsArgs,
}


def _create_project_definitions() -> dict[str, tuple[Any, Any]]:
    """
    Generate the create-project projection of ``ProjectModel``.

    Returns:
        Field definitions with ``project_name`` required, all other model
        fields optional, plus the MCP confirmation protocol fields.
    """
    definitions: dict[str, tuple[Any, Any]] = {}
    for name in _PROJECT_CREATE_FIELDS:
        definitions[name] = _generated_field(
            ProjectModel,
            name,
            required=name == "project_name",
            annotation=_PROJECT_ANNOTATIONS.get(name),
        )
    definitions["overwrite"] = (
        bool,
        Field(
            default=False,
            description=(
                "Replace an existing project at the same location (only if the user asked)."
            ),
        ),
    )
    definitions["confirm"] = (
        bool,
        Field(
            default=False,
            description=(
                "Confirmation protocol only: leave false to prepare/revise the configuration. "
                "Set true only in a later call after the user explicitly confirms the displayed "
                "revision. Never set true on the first create_project call."
            ),
        ),
    )
    definitions["revision"] = (
        int | None,
        Field(
            default=None,
            ge=1,
            description=(
                "Pending configuration revision returned by the prepare call. Required with "
                "confirm=true; a stale revision will not create a project."
            ),
        ),
    )
    return definitions


CreateProjectArgs = _generated_model(
    "CreateProjectArgs", _create_project_definitions()
)
CreateProjectArgs.__doc__ = (
    "Create-project fields generated from ProjectModel plus confirmation protocol fields."
)

UpdateProjectSettingsArgs = _generated_model(
    "UpdateProjectSettingsArgs",
    _patch_definitions(
        ProjectModel,
        _PROJECT_MUTABLE_FIELDS,
        annotations=_PROJECT_ANNOTATIONS,
    ),
    base=_SettingsPatchBase,
)
UpdateProjectSettingsArgs.__doc__ = (
    "Mutable ProjectModel settings generated from the core dataclass."
)


class JobStatusArgs(BaseModel):
    """Poll a background job started by a long-running tool."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(
        description=(
            "The job_id returned with a status=pending result, copied exactly."
        )
    )


class ProjectOpenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str | None = Field(
        default=None,
        description=(
            "Existing project name under the default store when storage_dir is omitted. "
            "Use the name the user gave; do not invent. "
            "project_open only switches projects — it does not import DICOM. "
            "To import a file use import_file with file_path on an already-open project."
        ),
        **_FIELD_CONSTRAINTS["project_name"],
    )
    storage_dir: str | None = Field(
        default=None,
        description=(
            "Absolute project directory (or folder containing ProjectModel.json), "
            "only if the user provided it. Not a DICOM file path — use import_file for that."
        ),
    )
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
            "Required from the user — never invent or copy documentation placeholders. "
            "Requires an already-open project."
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
            "Absolute path to one DICOM file on this machine (argument name is file_path, "
            "not path). Required from the user — never invent or copy documentation placeholders. "
            "Project must already be open. "
            "Do not call project_open to import — call import_file with file_path only."
        ),
    )

    @field_validator("file_path")
    @classmethod
    def _file_abs(cls, v: str) -> str:
        return _require_user_absolute_path(v)


def _configure_remote_definitions() -> dict[str, tuple[Any, Any]]:
    """
    Generate the remote-node projection of ``DICOMNode``.

    Returns:
        Field definitions for one remote node. ``role`` is added by the tool
        because it is the ``ProjectModel.remote_scps`` dictionary key, not a
        ``DICOMNode`` field.
    """
    definitions: dict[str, tuple[Any, Any]] = {
        "ip": _generated_field(
            DICOMNode,
            "ip",
            required=True,
            description=(
                "Remote PACS IPv4 exactly as the user stated "
                f"({IP_MIN_CHARS}–{IP_MAX_CHARS} chars). Field name is ip — never host, "
                "hostname, or address. Ask DIMSE vs DICOMweb for this role before calling "
                "if unknown."
            ),
        ),
        "port": _generated_field(
            DICOMNode,
            "port",
            required=True,
            description=(
                f"Remote DICOM (DIMSE) port {IP_PORT_MIN}–{IP_PORT_MAX} (integer from the "
                "user). Field name is port — not host. For DICOMweb HTTP use http_port "
                "instead of inventing a protocol/path key; still supply port/aet as "
                "required node fields."
            ),
        ),
        "aet": _generated_field(
            DICOMNode,
            "aet",
            required=True,
            description=(
                "Remote AE title "
                f"{AET_MIN_CHARS}–{AET_MAX_CHARS} chars exactly as the user stated. "
                "Field name is aet — never aetitle, ae_title, or AETitle. Do not invent "
                "AET; if missing for DIMSE, ask before calling."
            ),
        ),
        "role": (
            RemoteScpRole,
            Field(
                default=RemoteScpRole.QUERY,
                description=(
                    "Remote SCP role: QUERY (find/move) or EXPORT. Configure each role separately."
                ),
            ),
        ),
    }
    for name in ("dicomweb", "http_port", "http_path", "use_https", "username", "password"):
        field = _MODEL_FIELDS[DICOMNode][name]
        definitions[name] = _generated_field(
            DICOMNode,
            name,
            default=field.default,
        )
    return definitions


ConfigureRemoteArgs = _generated_model(
    "ConfigureRemoteArgs", _configure_remote_definitions()
)
ConfigureRemoteArgs.__doc__ = "Remote DICOMNode fields generated from the core dataclass."


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
