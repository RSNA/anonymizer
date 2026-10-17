"""OCR whitelist and exclude-zone project file I/O."""

from __future__ import annotations

import json
from pathlib import Path

from anonymizer.utils.translate import get_current_language_code, locales_dir


def default_whitelist_path(modality_code: str) -> Path:
    """
    Bundled default whitelist path for a modality.

    Args:
        modality_code: DICOM modality code (file stem uses lower-case).

    Returns:
        Path under the current locale ``whitelists/`` directory.
    """
    return locales_dir() / str(get_current_language_code() or "en_US") / "whitelists" / (modality_code.lower() + ".txt")


def project_whitelist_path(project_dir: Path, modality_code: str) -> Path:
    """
    Project override whitelist path for a modality.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.

    Returns:
        Path under ``project_dir/whitelists/``.
    """
    return project_dir / Path("whitelists/" + modality_code.lower() + ".txt")


def project_whitelist_options_path(project_dir: Path, modality_code: str) -> Path:
    """
    Project whitelist options JSON path for a modality.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.

    Returns:
        Options JSON path under ``project_dir/whitelists/``.
    """
    return project_dir / Path("whitelists/" + modality_code.lower() + ".options.json")


def project_exclude_zones_path(project_dir: Path, modality_code: str) -> Path:
    """
    Project exclude-rects JSON path for a modality.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.

    Returns:
        Exclude JSON path under ``project_dir/whitelists/``.
    """
    return project_dir / Path("whitelists/" + modality_code.lower() + ".exclude.json")


def load_whitelist_from_txt(filepath: Path) -> list[str]:
    """
    Load unique upper-cased whitelist terms from a text file.

    Args:
        filepath: Whitelist ``.txt`` path.

    Returns:
        Ordered list of unique upper-case terms (comments and blanks skipped).

    Raises:
        ValueError: If ``filepath`` is not a file.
    """
    whitelist = []
    if not filepath.is_file():
        raise ValueError(f"{filepath} is not a valid file")

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            word_part = line.split("#", 1)[0]
            word = word_part.strip()
            if word and word not in whitelist:
                whitelist.append(word.upper())

    return whitelist


def save_whitelist_to_txt(filepath: Path, whitelist: list[str]) -> None:
    """
    Write whitelist terms one per line.

    Args:
        filepath: Destination ``.txt`` path.
        whitelist: Terms to write.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        for word in whitelist:
            f.write(word + "\n")


def save_project_whitelist(project_dir: Path, modality_code: str, whitelist: list[str]) -> Path:
    """
    Save the project whitelist under ``project_dir/whitelists/<modality>.txt``.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.
        whitelist: Terms to save.

    Returns:
        Path written.

    Raises:
        ValueError: If whitelist is empty or ``project_dir`` is not a directory.
    """
    if not whitelist:
        raise ValueError("Whitelist is empty")
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")

    filepath = project_whitelist_path(project_dir, modality_code)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    save_whitelist_to_txt(filepath, whitelist)
    return filepath


def load_project_whitelist(project_dir: Path, modality_code: str) -> list[str]:
    """
    Load the project whitelist for a modality.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.

    Returns:
        Whitelist terms.
    """
    return load_whitelist_from_txt(project_whitelist_path(project_dir, modality_code))


def _normalized_exclude_rect(rect: object) -> dict | None:
    """Return a normalized ``x1/y1/x2/y2`` dict, or None if invalid."""
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

    Missing file → empty list. Accepts ``{"rects": [...]}`` and the older
    named ``{"zones": [{"rects": [...]}]}`` shape.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.

    Returns:
        List of normalized rect dicts.
    """
    path = project_exclude_zones_path(project_dir, modality_code)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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
    Write exclude rects for a modality (creates ``whitelists/``).

    Empty ``rects`` removes the modality exclude file when present.

    Args:
        project_dir: Project storage directory.
        modality_code: DICOM modality code.
        rects: Rect dicts to persist.

    Returns:
        Path written or removed.

    Raises:
        ValueError: If ``project_dir`` is not a directory.
    """
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")
    path = project_exclude_zones_path(project_dir, modality_code)
    if not rects:
        if path.is_file():
            path.unlink()
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rects": rects}, indent=2) + "\n", encoding="utf-8")
    return path


def load_default_whitelist(modality_code: str) -> list[str]:
    """
    Load the bundled default whitelist for a modality.

    CR and MG share the DX default list.

    Args:
        modality_code: DICOM modality code.

    Returns:
        Whitelist terms.
    """
    if modality_code == "CR" or modality_code == "MG":
        modality_code = "DX"
    return load_whitelist_from_txt(default_whitelist_path(modality_code))
