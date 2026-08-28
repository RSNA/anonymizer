"""
Storage utilities for the anonymizer application.

Includes DICOM path helpers, whitelist I/O, and thread-safe progress tracking for
AI model downloads (any feature — OCR, segmentation, future weights).
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from openpyxl import Workbook, load_workbook
from openpyxl.workbook.child import _WorkbookChild
from openpyxl.worksheet.worksheet import Worksheet

from anonymizer.utils.translate import get_current_language_code

logger = logging.getLogger(__name__)

DICOM_FILE_SUFFIX = ".dcm"


def is_hidden_name(name: str) -> bool:
    """True for dot-prefixed file or directory names (e.g. ``.DS_Store``, ``.git``)."""
    return bool(name) and name.startswith(".")


def is_hidden_path(path: str | Path) -> bool:
    """True when any path component is a hidden file or directory name."""
    return any(is_hidden_name(part) for part in Path(path).parts)


def list_import_directory_files(root_dir: str | Path) -> list[str]:
    """List files under ``root_dir``, skipping hidden directories and files."""
    root = os.fspath(root_dir)
    file_paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not is_hidden_name(name)]
        for filename in filenames:
            if is_hidden_name(filename):
                continue
            file_paths.append(os.path.join(dirpath, filename))
    return file_paths


def count_studies_series_images(patient_path: str) -> tuple[int, int, int]:
    """
    Counts the number of studies, series, and images in a given patient directory in the anonymizer store

    Args:
        patient_path (str): The path to the patient directory.

    Returns:
        A tuple containing the number of studies, series, and images in the patient directory.
    """
    study_count = 0
    series_count = 0
    image_count = 0

    for root, dirs, files in os.walk(patient_path):
        if root == patient_path:
            study_count += len(dirs)
        else:
            series_count += len(dirs)
        for file in files:
            if file.endswith(DICOM_FILE_SUFFIX):
                image_count += 1

    return study_count, series_count, image_count


def count_series(base_dir: str, patient_ids: Optional[list[str]] = None) -> int:
    """
    Counts the total number of series across multiple patients in the anonymizer store.

    Args:
        base_dir (str): The base directory containing patient folders.
        patient_ids (list[str]): A list of patient IDs, if None count number of series for ALL patients

    Returns:
        The total number of series across all patient directories in patient_id list
    """
    total_series = 0

    base_path = Path(base_dir)
    if not base_path.is_dir():
        raise ValueError(f"{base_dir} is not a valid directory")

    # If patient_ids not specified, iterate through ALL patients
    if patient_ids is None:
        patient_ids = [str(object=p) for p in base_path.iterdir() if p.is_dir()]

    for patient_id in patient_ids:
        patient_path: Path = base_path / patient_id
        if not patient_path.exists():
            continue

        for root, dirs, _ in os.walk(patient_path):
            if root != str(object=patient_path):  # Count series in subdirectories only
                total_series += len(dirs)

    return total_series


def get_dcm_files(root_path: str | Path) -> list[Path]:
    """
    Retrieves paths of each dicom file from a root path which could be at patient, study or series level.

    Args:
        root_path (str | Path): The root path to start the search for dicom files.

    Returns:
        List of Path objects
    """
    root_path = Path(root_path)  # Ensure root_path is a Path object

    return [
        Path(root) / file for root, _, files in os.walk(root_path) for file in files if file.endswith(DICOM_FILE_SUFFIX)
    ]


def count_study_images(base_dir: Path, anon_pt_id: str, study_uid: str) -> int:
    """
    Counts the number of images stored in a given study directory.

    Args:
        anon_uid (str): The anonymous patient ID.
        study_uid (str): The study UID.

    Returns:
        The number of images stored in the study directory.
    """
    study_path = Path(base_dir, anon_pt_id, study_uid)
    image_count = 0

    for _, _, files in os.walk(study_path):
        for file in files:
            if file.endswith(DICOM_FILE_SUFFIX):
                image_count += 1

    return image_count


def count_quarantine_images(quarantine_path: Path) -> int:
    """
    Counts the number of images stored in the quarantine directory.

    Args:
        quarantine_path (Path): The base directory containing the quarantine folder.

    Returns:
        The number of images stored in the quarantine directory.
    """

    if not quarantine_path.is_dir():
        return 0

    image_count = 0
    for _, _, files in os.walk(quarantine_path):
        for file in files:
            if file.__contains__(DICOM_FILE_SUFFIX):
                image_count += 1

    return image_count


@dataclass
class JavaAnonymizerExportedStudy:
    ANON_PatientName: str
    ANON_PatientID: str
    PHI_PatientName: str
    PHI_PatientID: str
    DateOffset: str
    ANON_StudyDate: str
    PHI_StudyDate: str
    ANON_Accession: str
    PHI_Accession: str
    ANON_StudyInstanceUID: str
    PHI_StudyInstanceUID: str


def read_java_anonymizer_index_xlsx(filename: str) -> list[JavaAnonymizerExportedStudy]:
    """
    Read data from the Java Anonymizer exported patient index file
    containing a single workbook & sheet with fields as per the JavaAnonymizerExportedStudy dataclass.

    Args:
        filename (str): The path to the Excel file.

    Returns:
        List of JavaAnonymizerExportedStudy dataclass objects.

    Raises:
        ValueError: If no active sheet is found in the workbook.
        FileNotFoundError: If the file is not found.

    If the sheet is empty, an empty list is returned.
    """

    workbook: Workbook = load_workbook(filename)
    sheet: Union[_WorkbookChild, None] = workbook.active
    data: list[JavaAnonymizerExportedStudy] = []

    if sheet is None or not isinstance(sheet, Worksheet):
        raise ValueError("No active sheet found in the workbook")

    for row in sheet.iter_rows(values_only=True, min_row=2):
        str_row = [str(item) if item is not None else "" for item in row]
        data.append(JavaAnonymizerExportedStudy(*str_row))

    return data


def default_whitelist_path(modality_code: str) -> Path:
    return Path(
        "assets/locales/"
        + str(get_current_language_code() or "en_US")
        + "/whitelists/"
        + modality_code.lower()
        + ".txt"
    )


def project_whitelist_path(project_dir: Path, modality_code: str) -> Path:
    return project_dir / Path("whitelists/" + modality_code.lower() + ".txt")


def project_whitelist_options_path(project_dir: Path, modality_code: str) -> Path:
    return project_dir / Path("whitelists/" + modality_code.lower() + ".options.json")


def load_modality_whitelist_match_settings(
    project_dir: Path | None,
    modality_code: str | None,
):
    """Load per-modality OCR whitelist match settings from sidecar JSON."""
    from anonymizer.controller.ai.remove_pixel_phi import (
        OcrWhitelistMatchSettings,
        default_whitelist_match_settings,
    )

    if not modality_code or project_dir is None:
        return default_whitelist_match_settings()
    options_path = project_whitelist_options_path(project_dir, modality_code)
    if options_path.is_file():
        try:
            data = json.loads(options_path.read_text(encoding="utf-8"))
            return OcrWhitelistMatchSettings.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Could not load whitelist match settings from %s: %s", options_path, exc)
    return default_whitelist_match_settings()


def save_modality_whitelist_match_settings(
    project_dir: Path,
    modality_code: str,
    settings,
) -> Path:
    """Persist per-modality OCR whitelist match settings to sidecar JSON."""
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")
    filepath = project_whitelist_options_path(project_dir, modality_code)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
    return filepath


def project_dir_from_series_path(series_path: Path) -> Path | None:
    """Return project storage_dir from a series directory under ``public/``."""
    if len(series_path.parents) <= 3:
        return None
    return series_path.parents[3]


def load_whitelist_from_txt(filepath: Path) -> list[str]:
    whitelist = []
    if not filepath.is_file():
        raise ValueError(f"{filepath} is not a valid file")

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            # 1. Remove comment part first (split at #, take first part)
            word_part = line.split("#", 1)[0]
            # 2. Strip whitespace from the word part
            word = word_part.strip()
            # 3. Add if not empty
            if word and word not in whitelist:
                whitelist.append(word.upper())

    return whitelist


def save_whitelist_to_txt(filepath: Path, whitelist: list[str]) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        for word in whitelist:
            f.write(word + "\n")


def save_project_whitelist(project_dir: Path, modality_code: str, whitelist: list[str]) -> Path:
    """
    Save the project whitelist to a text file in /project_dir/whitelists/modality_code.txt.

    Args:
        project_dir (Path): The main project directory
        modality_code (str): The modality code for which to save the whitelist.
        whitelist (list[str]): The whitelist to save.
    """
    if not whitelist:
        raise ValueError("Whitelist is empty")
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")

    filepath = project_whitelist_path(project_dir, modality_code)
    # Ensure the parent directory exists
    filepath.parent.mkdir(parents=True, exist_ok=True)
    # Save the whitelist to the file
    save_whitelist_to_txt(filepath, whitelist)
    return filepath


def load_project_whitelist(project_dir: Path, modality_code: str) -> list[str]:
    """
    Load the project whitelist for a given modality code.

    Args:
        project_dir (Path): The main project directory
        modality_code (str): The modality code for which to load the whitelist.

    Returns:
        A set of whitelisted terms.
    """
    return load_whitelist_from_txt(project_whitelist_path(project_dir, modality_code))


def load_default_whitelist(modality_code: str) -> list[str]:
    """
    Load the default whitelist for a given modality code.

    Args:
        modality_code (str): The modality code for which to load the whitelist.

    Returns:
        A set of whitelisted terms.
    """
    if modality_code == "CR" or modality_code == "MG":
        modality_code = "DX"
    return load_whitelist_from_txt(default_whitelist_path(modality_code))


# --- AI model download progress (thread-safe, feature-agnostic) ---

_download_lock = threading.Lock()


@dataclass(frozen=True)
class DownloadProgress:
    """Snapshot of one in-flight AI model download."""

    message: str = ""
    fraction: float | None = None


_download_progress: dict[str, DownloadProgress] = {}


def begin_model_download(download_id: str, *, message: str = "") -> None:
    """Register a model download under ``download_id`` (any stable feature key)."""
    with _download_lock:
        _download_progress[download_id] = DownloadProgress(message=message or "Downloading…", fraction=None)


def update_model_download(
    download_id: str,
    *,
    message: str | None = None,
    fraction: float | None | object = ...,
) -> None:
    """Update progress for an active download; no-op if ``download_id`` is unknown."""
    with _download_lock:
        current = _download_progress.get(download_id)
        if current is None:
            return
        new_message = current.message if message is None else message
        new_fraction = current.fraction if fraction is ... else fraction
        _download_progress[download_id] = DownloadProgress(message=new_message, fraction=new_fraction)


def end_model_download(download_id: str) -> None:
    """Clear progress for ``download_id`` when a download finishes or fails."""
    with _download_lock:
        _download_progress.pop(download_id, None)


def get_model_download_progress(download_id: str) -> DownloadProgress | None:
    with _download_lock:
        return _download_progress.get(download_id)


def is_model_download_active(download_id: str) -> bool:
    return get_model_download_progress(download_id) is not None


def any_model_download_active() -> bool:
    with _download_lock:
        return bool(_download_progress)


def _format_download_bytes(num: float) -> str:
    if num < 1024:
        return f"{num:.0f}B"
    num /= 1024
    if num < 1024:
        return f"{num:.1f}KB"
    num /= 1024
    if num < 1024:
        return f"{num:.1f}MB"
    num /= 1024
    return f"{num:.1f}GB"


class _DownloadStdoutCapture(io.TextIOBase):
    """Forward stdout while reporting stripped lines to a progress callback."""

    def __init__(self, original: io.TextIOBase, on_line: Callable[[str], None]) -> None:
        self._original = original
        self._on_line = on_line
        self._buffer = ""

    def write(self, s: str) -> int:
        self._original.write(s)
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            text = line.strip()
            if text:
                self._on_line(text)
        return len(s)

    def flush(self) -> None:
        self._original.flush()
        text = self._buffer.strip()
        if text:
            self._on_line(text)
            self._buffer = ""

    def __getattr__(self, name: str):
        return getattr(self._original, name)


@contextlib.contextmanager
def track_tqdm_model_download(
    download_id: str,
    *,
    start_message: str = "Downloading…",
    label: str = "",
    tqdm_module: object,
    on_progress: Callable[[str, float | None], None] | None = None,
    manage_lifecycle: bool = True,
) -> Iterator[None]:
    """Capture tqdm/stdout progress while a third-party library downloads model weights.

    Args:
        download_id: Stable key for UI polling (e.g. ``remove_pixel_phi``, ``enable_harmonize``).
        start_message: Initial status line (used when ``label`` is empty).
        label: Optional model name shown after ``Downloading:`` with byte progress.
        tqdm_module: Module object whose ``tqdm`` attribute will be patched (e.g. ``totalsegmentator.libs``).
        on_progress: Optional ``(message, fraction)`` callback on each update.
        manage_lifecycle: When False, only report updates; caller owns begin/end_model_download.
    """
    from tqdm import tqdm as orig_tqdm

    resolved_start = f"Downloading: {label}…" if label else start_message
    if manage_lifecycle or get_model_download_progress(download_id) is None:
        begin_model_download(download_id, message=resolved_start)
    if on_progress is not None:
        on_progress(resolved_start, None)

    def _progress_message(byte_part: str) -> str:
        if label:
            return f"Downloading: {label} — {byte_part}"
        return f"Downloading: {byte_part}"

    def _report(message: str, *, fraction: float | None | object = ...) -> None:
        resolved = None if fraction is ... else fraction
        update_model_download(download_id, message=message, fraction=fraction)
        if on_progress is not None:
            on_progress(message, resolved)

    class ProgressTqdm(orig_tqdm):
        monitor_interval = 0

        def update(self, n=1):
            result = super().update(n)
            if self.total:
                fraction = min(1.0, self.n / self.total)
                byte_part = f"{_format_download_bytes(self.n)}/{_format_download_bytes(self.total)}"
            else:
                fraction = None
                byte_part = _format_download_bytes(self.n)
            _report(_progress_message(byte_part), fraction=fraction)
            return result

        def close(self):
            return super().close()

    original_tqdm = tqdm_module.tqdm
    tqdm_module.tqdm = ProgressTqdm
    captured_stdout = _DownloadStdoutCapture(sys.stdout, lambda line: _report(line))
    saved_stdout = sys.stdout
    sys.stdout = captured_stdout
    try:
        yield
    finally:
        sys.stdout = saved_stdout
        captured_stdout.flush()
        tqdm_module.tqdm = original_tqdm
        if manage_lifecycle:
            end_model_download(download_id)
