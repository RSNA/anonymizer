"""Plain validators for project settings (MCP / ops). Match GUI min/max/charset.

Reject invalid values (do not clamp). Keep limits in ``settings_limits``.
"""

from __future__ import annotations

from typing import Any

from anonymizer.model import settings_limits as lim
from anonymizer.model.project import DICOMNode, NetworkTimeouts
from anonymizer.utils.modalities import get_modalities
from anonymizer.utils.network import is_valid_ip
from anonymizer.utils.translate import language_to_code


class SettingsValidationError(ValueError):
    """Field-level settings validation failure."""


def _chars_ok(value: str, charset: str) -> bool:
    return all(c in charset for c in value)


def _require_len(field: str, value: str, min_chars: int, max_chars: int) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not (min_chars <= len(text) <= max_chars):
        raise SettingsValidationError(
            f"{field} must be {min_chars}–{max_chars} characters (got {len(text)})"
        )
    return text


def validate_project_name(value: str) -> str:
    text = _require_len(
        "project_name", value, lim.PROJECT_NAME_MIN_CHARS, lim.PROJECT_NAME_MAX_CHARS
    )
    if not _chars_ok(text, lim.PROJECT_NAME_CHARSET):
        raise SettingsValidationError(
            "project_name allows letters, digits, space, hyphen, and period only"
        )
    return text


def validate_site_id(value: str) -> str:
    text = _require_len("site_id", value, lim.SITE_ID_MIN_CHARS, lim.SITE_ID_MAX_CHARS)
    if not _chars_ok(text, lim.SITE_ID_CHARSET):
        raise SettingsValidationError("site_id allows digits, hyphen, and period only")
    return text


def validate_uid_root(value: str) -> str:
    text = _require_len("uid_root", value, lim.UID_ROOT_MIN_CHARS, lim.UID_ROOT_MAX_CHARS)
    if not _chars_ok(text, lim.UID_ROOT_CHARSET):
        raise SettingsValidationError("uid_root allows digits and period only")
    return text


def validate_language_code(value: str) -> str:
    code = (value or "").strip()
    allowed = set(language_to_code.values())
    if code not in allowed:
        raise SettingsValidationError(
            f"language_code must be one of {sorted(allowed)} (got {code!r})"
        )
    return code


def validate_ip(value: str, *, field: str = "ip") -> str:
    text = _require_len(field, value, lim.IP_MIN_CHARS, lim.IP_MAX_CHARS)
    if not _chars_ok(text, lim.IP_CHARSET):
        raise SettingsValidationError(f"{field} allows digits and period only (IPv4)")
    if not is_valid_ip(text):
        raise SettingsValidationError(f"{field} is not a valid IPv4 address: {text!r}")
    return text


def validate_port(value: int | float, *, field: str = "port") -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{field} must be an integer") from exc
    if not (lim.IP_PORT_MIN <= port <= lim.IP_PORT_MAX):
        raise SettingsValidationError(
            f"{field} must be {lim.IP_PORT_MIN}–{lim.IP_PORT_MAX} (got {port})"
        )
    return port


def validate_aet(value: str, *, field: str = "aet") -> str:
    text = _require_len(field, value, lim.AET_MIN_CHARS, lim.AET_MAX_CHARS)
    if not _chars_ok(text, lim.AET_CHARSET):
        raise SettingsValidationError(f"{field} contains characters not allowed for AE title")
    return text


def validate_http_path(value: str, *, field: str = "http_path") -> str:
    text = (value or "").strip()
    if not (lim.HTTP_PATH_MIN_CHARS <= len(text) <= lim.HTTP_PATH_MAX_CHARS):
        raise SettingsValidationError(
            f"{field} must be {lim.HTTP_PATH_MIN_CHARS}–{lim.HTTP_PATH_MAX_CHARS} characters"
        )
    if not _chars_ok(text, lim.HTTP_PATH_CHARSET):
        raise SettingsValidationError(f"{field} contains characters not allowed for HTTP path")
    return text


def validate_timeout(
    value: int | float,
    *,
    field: str,
    min_v: int,
    max_v: int,
) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{field} must be a number") from exc
    if not (min_v <= num <= max_v):
        raise SettingsValidationError(f"{field} must be {min_v}–{max_v} seconds (got {num})")
    return num


def validate_network_timeouts(
    *,
    tcp_connection: int | float | None = None,
    acse: int | float | None = None,
    dimse: int | float | None = None,
    network: int | float | None = None,
    base: NetworkTimeouts | None = None,
) -> NetworkTimeouts:
    """Validate provided timeout fields; fill omitted from ``base`` or factory defaults."""
    from anonymizer.model.project import ProjectModel

    src = base if base is not None else ProjectModel.default_timeouts()
    tcp = (
        validate_timeout(
            tcp_connection,
            field="network_timeouts.tcp_connection",
            min_v=lim.TCP_TIMEOUT_MIN,
            max_v=lim.TCP_TIMEOUT_MAX,
        )
        if tcp_connection is not None
        else float(src.tcp_connection)
    )
    acse_v = (
        validate_timeout(
            acse, field="network_timeouts.acse", min_v=lim.ACSE_TIMEOUT_MIN, max_v=lim.ACSE_TIMEOUT_MAX
        )
        if acse is not None
        else float(src.acse)
    )
    dimse_v = (
        validate_timeout(
            dimse,
            field="network_timeouts.dimse",
            min_v=lim.DIMSE_TIMEOUT_MIN,
            max_v=lim.DIMSE_TIMEOUT_MAX,
        )
        if dimse is not None
        else float(src.dimse)
    )
    net_v = (
        validate_timeout(
            network,
            field="network_timeouts.network",
            min_v=lim.NETWORK_TIMEOUT_MIN,
            max_v=lim.NETWORK_TIMEOUT_MAX,
        )
        if network is not None
        else float(src.network)
    )
    return NetworkTimeouts(tcp, acse_v, dimse_v, net_v)


def validate_local_scp(
    *,
    ip: str | None = None,
    port: int | None = None,
    aet: str | None = None,
    base: DICOMNode | None = None,
) -> DICOMNode:
    """Validate local SCP fields; fill omitted from ``base`` or factory default."""
    from anonymizer.model.project import ProjectModel

    src = base if base is not None else ProjectModel.default_local_server()
    resolved_ip = validate_ip(ip if ip is not None else src.ip)
    resolved_port = validate_port(port if port is not None else src.port)
    resolved_aet = validate_aet(aet if aet is not None else src.aet)
    return DICOMNode(resolved_ip, resolved_port, resolved_aet, True)


def validate_remote_node(
    *,
    ip: str,
    port: int,
    aet: str,
    dicomweb: bool = False,
    http_port: int | None = None,
    http_path: str | None = None,
    use_https: bool = False,
    username: str | None = None,
    password: str | None = None,
) -> DICOMNode:
    """Validate QUERY/EXPORT remote fields (DIMSE or DICOMweb)."""
    resolved_ip = validate_ip(ip)
    resolved_port = validate_port(port)
    resolved_aet = validate_aet(aet)
    web = bool(dicomweb)
    resolved_http_port = validate_port(http_port if http_port is not None else 8042, field="http_port")
    resolved_http_path = validate_http_path(
        http_path if http_path is not None else "/dicom-web", field="http_path"
    )
    user = (username or "").strip()
    pwd = password or ""
    if web and bool(user) != bool(pwd):
        raise SettingsValidationError("username and password must both be set or both empty")
    return DICOMNode(
        resolved_ip,
        resolved_port,
        resolved_aet,
        False,
        dicomweb=web,
        http_port=resolved_http_port,
        http_path=resolved_http_path,
        use_https=bool(use_https),
        username=user if web else "",
        password=pwd if web else "",
    )


def validate_modality_codes(modalities: list[str]) -> list[str]:
    catalog = get_modalities()
    bad = [m for m in modalities if m not in catalog]
    if bad:
        raise SettingsValidationError(
            f"Unknown modality code(s): {bad}. Use codes from get_modalities() / project defaults."
        )
    return list(modalities)


def validate_transfer_syntaxes(values: list[str], *, allowed: list[str]) -> list[str]:
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    if not cleaned:
        raise SettingsValidationError("transfer_syntaxes must be a non-empty list when provided")
    allowed_set = set(allowed)
    bad = [v for v in cleaned if v not in allowed_set]
    if bad:
        raise SettingsValidationError(
            f"Unknown transfer_syntax UID(s): {bad}. Use project default transfer syntax UIDs."
        )
    return cleaned


def timeouts_dict(timeouts: NetworkTimeouts) -> dict[str, float]:
    return {
        "tcp_connection": float(timeouts.tcp_connection),
        "acse": float(timeouts.acse),
        "dimse": float(timeouts.dimse),
        "network": float(timeouts.network),
    }


def settings_defaults_payload() -> dict[str, Any]:
    """Factory defaults + short help for the interactive setup wizard."""
    from anonymizer.model.project import ProjectModel
    from anonymizer.utils.translate import code_to_language

    model = ProjectModel()
    scp = model.scp
    return {
        "defaults": {
            "language_code": model.language_code,
            "site_id": "(auto-generated at create if omitted)",
            "uid_root": model.uid_root,
            "modalities": list(model.modalities),
            "transfer_syntaxes": list(model.transfer_syntaxes),
            "scp": {"ip": scp.ip, "port": scp.port, "aet": scp.aet},
            "network_timeouts": timeouts_dict(model.network_timeouts),
        },
        "language_codes": sorted(language_to_code.values()),
        "languages": {code: name for code, name in code_to_language.items()},
        "ranges": {
            "project_name": f"{lim.PROJECT_NAME_MIN_CHARS}–{lim.PROJECT_NAME_MAX_CHARS} chars; letters/digits/space/-/.",
            "site_id": f"{lim.SITE_ID_MIN_CHARS}–{lim.SITE_ID_MAX_CHARS} chars; digits/-/.",
            "uid_root": f"{lim.UID_ROOT_MIN_CHARS}–{lim.UID_ROOT_MAX_CHARS} chars; digits/.",
            "ip": f"IPv4, {lim.IP_MIN_CHARS}–{lim.IP_MAX_CHARS} chars",
            "port": f"{lim.IP_PORT_MIN}–{lim.IP_PORT_MAX}",
            "aet": f"{lim.AET_MIN_CHARS}–{lim.AET_MAX_CHARS} chars",
            "timeouts_s": {
                "tcp_connection": f"{lim.TCP_TIMEOUT_MIN}–{lim.TCP_TIMEOUT_MAX}",
                "acse": f"{lim.ACSE_TIMEOUT_MIN}–{lim.ACSE_TIMEOUT_MAX}",
                "dimse": f"{lim.DIMSE_TIMEOUT_MIN}–{lim.DIMSE_TIMEOUT_MAX}",
                "network": f"{lim.NETWORK_TIMEOUT_MIN}–{lim.NETWORK_TIMEOUT_MAX}",
            },
        },
        "help": {
            "dimse_vs_dicomweb": (
                "For each PACS role (QUERY and EXPORT), ask whether the remote uses "
                "classic DICOM networking (DIMSE SCP: ip + DICOM port + AET) or DICOMweb "
                "(ip + HTTP(S) port + http_path, optional Basic auth; set dicomweb=true). "
                "Use one port appropriate to the chosen mode — not both DIMSE and HTTP ports. "
                "Do not assume DICOMweb unless the user chose it or supplied HTTP details."
            ),
            "identity_locked": (
                "project_name, storage_dir, site_id, and uid_root are fixed after create; "
                "use update_project_settings only for language, modalities, transfer_syntaxes, "
                "local scp, and network_timeouts."
            ),
        },
    }
