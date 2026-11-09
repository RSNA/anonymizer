"""OCR whitelist, match-mode, and exclude-zone project file I/O.

Path helpers and txt read/write stay private. Storage:
project_dir/whitelists/<modality>.txt, <modality>.options.json, exclude JSON.

Public API
----------
load_modality_whitelist(project_dir: Path | None, modality: str | None) -> list[str]
    Effective modality whitelist (project override else bundled default).

save_project_whitelist(project_dir: Path, modality_code: str, whitelist: list[str]) -> Path
    Save project whitelist under project_dir/whitelists/<modality>.txt.

load_default_whitelist(modality_code: str) -> list[str]
    Bundled default whitelist (Series View reset-to-default).

load_modality_phi_match_mode(project_dir: Path | None, modality_code: str | None) -> PhiMatchMode
    Load PhiMatchMode from options JSON; missing/invalid/custom → STANDARD.

save_modality_phi_match_mode(project_dir: Path, modality_code: str, mode: PhiMatchMode) -> Path
    Persist {"match_mode": "<value>"} only.

load_project_exclude_rects(project_dir: Path, modality_code: str) -> list[dict]
    Load normalized exclude rects for a modality.

save_project_exclude_rects(project_dir: Path, modality_code: str, rects: list[dict]) -> Path
    Write exclude rects for a modality.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.utils.translate import get_current_language_code, locales_dir

logger = logging.getLogger(__name__)


def _default_whitelist_path(modality_code: str) -> Path:
    return locales_dir() / get_current_language_code() / "whitelists" / (modality_code.lower() + ".txt")


def _project_whitelist_path(project_dir: Path, modality_code: str) -> Path:
    return project_dir / Path("whitelists/" + modality_code.lower() + ".txt")


def _project_whitelist_options_path(project_dir: Path, modality_code: str) -> Path:
    return project_dir / Path("whitelists/" + modality_code.lower() + ".options.json")


def _project_exclude_zones_path(project_dir: Path, modality_code: str) -> Path:
    return project_dir / Path("whitelists/" + modality_code.lower() + ".exclude.json")


def _load_whitelist_from_txt(filepath: Path) -> list[str]:
    whitelist: list[str] = []
    if not filepath.is_file():
        raise ValueError(f"{filepath} is not a valid file")
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            word_part = line.split("#", 1)[0]
            word = word_part.strip()
            if word and word not in whitelist:
                whitelist.append(word.upper())
    return whitelist


def _save_whitelist_to_txt(filepath: Path, whitelist: list[str]) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        for word in whitelist:
            f.write(word + "\n")


def save_project_whitelist(project_dir: Path, modality_code: str, whitelist: list[str]) -> Path:
    """
    Save the project whitelist under project_dir/whitelists/<modality>.txt.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.
        whitelist: Terms to save.

    Returns:
        Path written.

    Raises:
        ValueError: If whitelist is empty or project_dir is not a directory.
    """
    if not whitelist:
        raise ValueError("Whitelist is empty")
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")
    filepath = _project_whitelist_path(project_dir, modality_code)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    _save_whitelist_to_txt(filepath, whitelist)
    return filepath


def load_default_whitelist(modality_code: str) -> list[str]:
    """
    Load the bundled default whitelist for a modality.

    CR shares the DX default list. PT shares the CT default list. MG has its
    own mammography view list.

    Args:
        modality_code: DICOM modality code.

    Returns:
        Whitelist terms.
    """
    code = modality_code
    if code == "CR":
        code = "DX"
    elif code == "PT":
        code = "CT"
    return _load_whitelist_from_txt(_default_whitelist_path(code))


def load_modality_whitelist(project_dir: Path | None, modality: str | None) -> list[str]:
    """
    Effective modality whitelist (project override else bundled default).

    Args:
        project_dir: Project storage directory, or None.
        modality: DICOM modality code, or None.

    Returns:
        Whitelist terms (empty if modality missing or no file).
    """
    if not modality:
        return []
    if project_dir is not None:
        project_path = _project_whitelist_path(project_dir, modality)
        if project_path.is_file():
            try:
                return _load_whitelist_from_txt(project_path)
            except (FileNotFoundError, OSError, ValueError) as exc:
                logger.debug(f"Project whitelist not loaded for {modality}: {exc}")
    try:
        return load_default_whitelist(modality)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.debug(f"Default whitelist not loaded for {modality}: {exc}")
    return []


def load_modality_phi_match_mode(
    project_dir: Path | None,
    modality_code: str | None,
) -> PhiMatchMode:
    """
    Load PhiMatchMode from options JSON; missing/invalid/custom → STANDARD.

    Args:
        project_dir: Project storage directory, or None.
        modality_code: DICOM modality code, or None.

    Returns:
        Persisted mode or STANDARD.
    """
    if not modality_code or project_dir is None:
        return PhiMatchMode.STANDARD
    options_path = _project_whitelist_options_path(project_dir, modality_code)
    if not options_path.is_file():
        return PhiMatchMode.STANDARD
    try:
        data = json.loads(options_path.read_text(encoding="utf-8"))
        mode_raw = str(data.get("match_mode", PhiMatchMode.STANDARD.value)).strip().lower()
        if mode_raw == "custom":
            return PhiMatchMode.STANDARD
        return PhiMatchMode(mode_raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(f"Could not load PhiMatchMode from {options_path}: {exc}")
        return PhiMatchMode.STANDARD


def save_modality_phi_match_mode(
    project_dir: Path,
    modality_code: str,
    mode: PhiMatchMode,
) -> Path:
    """
    Persist {"match_mode": "<value>"} only.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.
        mode: Mode to save.

    Returns:
        Options JSON path written.

    Raises:
        ValueError: If project_dir is not a directory.
    """
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")
    filepath = _project_whitelist_options_path(project_dir, modality_code)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps({"match_mode": mode.value}, indent=2) + "\n", encoding="utf-8")
    return filepath


def _normalized_exclude_rect(rect: object) -> dict | None:
    if not isinstance(rect, dict):
        return None
    try:
        return {
            "x1": float(rect["x1"]),
            "y1": float(rect["y1"]),
            "x2": float(rect["x2"]),
            "y2": float(rect["y2"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def load_project_exclude_rects(project_dir: Path, modality_code: str) -> list[dict]:
    """
    Load normalized exclude rects for a modality.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.

    Returns:
        List of normalized rect dicts.
    """
    path = _project_exclude_zones_path(project_dir, modality_code)
    try:
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    raw: list = []
    if isinstance(data.get("rects"), list):
        raw = data["rects"]
    elif isinstance(data.get("zones"), list):
        for zone in data["zones"]:
            if isinstance(zone, dict) and isinstance(zone.get("rects"), list):
                raw.extend(zone["rects"])
    out: list[dict] = []
    for item in raw:
        cleaned = _normalized_exclude_rect(item)
        if cleaned:
            out.append(cleaned)
    return out


def save_project_exclude_rects(project_dir: Path, modality_code: str, rects: list[dict]) -> Path:
    """
    Write exclude rects for a modality (creates whitelists/).

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.
        rects: Rect dicts to persist.

    Returns:
        Path written or removed.

    Raises:
        ValueError: If project_dir is not a directory.
    """
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")
    path = _project_exclude_zones_path(project_dir, modality_code)
    if not rects:
        if path.is_file():
            path.unlink()
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rects": rects}, indent=2) + "\n", encoding="utf-8")
    return path
