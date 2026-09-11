"""Temp project + DICOM fixture helpers for screenshot capture."""

from __future__ import annotations

import logging
import socket
from pathlib import Path

from anonymizer.controller.project import ProjectController
from anonymizer.model.project import DICOMNode, ProjectModel
from anonymizer.utils.storage import list_import_directory_files
from anonymizer.utils.translate import get_current_language_code

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DCM_ROOT = REPO_ROOT / "tests" / "controller" / "assets" / "test_dcm_files"
CTP_LOOKUP_PROPERTIES = (
    REPO_ROOT / "tests" / "controller" / "assets" / "ctp_lookup" / "test_dcm_files_lookup.properties"
)


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# Orthanc configMacOS.json maps AE ANONYMIZER → localhost:1045 for C-MOVE.
ORTHANC_CMOVE_SCP_PORT = 1045


def preferred_scp_port() -> int:
    """Prefer port 1045 so Orthanc can C-MOVE to this capture project."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", ORTHANC_CMOVE_SCP_PORT))
            return ORTHANC_CMOVE_SCP_PORT
        except OSError:
            return free_tcp_port()


def create_capture_project(storage_dir: Path, *, project_name: str = "HelpScreenshots") -> Path:
    """Create a ProjectModel.json under ``storage_dir`` and return the project directory."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "private").mkdir(exist_ok=True)
    (storage_dir / "public").mkdir(exist_ok=True)

    port = preferred_scp_port()
    model = ProjectModel()
    model.language_code = get_current_language_code()
    model.project_name = project_name
    model.storage_dir = storage_dir
    # Help demos include ultrasound (blend Remove Text) as well as CR/DX/CT/MR.
    if "US" not in model.modalities:
        model.modalities = list(model.modalities) + ["US"]
        model.set_storage_classes_from_modalities()
    # Orthanc modality maps AE ANONYMIZER → localhost:1045; keep English AET
    # even when the UI language would translate it (e.g. ANONYMISIERER).
    model.scp = DICOMNode("127.0.0.1", port, "ANONYMIZER", True)
    model.scu = DICOMNode("127.0.0.1", 0, "ANONYMIZER", True)
    # CT_Head_With_Contrast fixtures are JPEG 2000; Orthanc seed/C-MOVE need it.
    for uid in ("1.2.840.10008.1.2.4.90", "1.2.840.10008.1.2.4.91"):
        if uid not in model.transfer_syntaxes:
            model.transfer_syntaxes.append(uid)

    controller = ProjectController(model)
    controller.save_model()
    logger.info("Created capture project at %s (SCP port %s)", storage_dir, port)
    return storage_dir


def fixture_dirs() -> dict[str, Path]:
    """Named test DICOM directories used by help screenshots."""
    us_rgb = TEST_DCM_ROOT / "us_rgb_single_frame"
    return {
        "test_dcm_files": TEST_DCM_ROOT,
        "davidson_cxr": TEST_DCM_ROOT / "davidson_cxr",
        "CT_Head_With_Contrast": TEST_DCM_ROOT / "CT_Head_With_Contrast",
        "chest": TEST_DCM_ROOT / "synthetic_CT_chest",
        "head": TEST_DCM_ROOT / "synthetic_CT_head",
        "abdomen": TEST_DCM_ROOT / "synthetic_CT_abdomen",
        "us": us_rgb,
        "us_rgb_single_frame": us_rgb,
        "us_mf": TEST_DCM_ROOT / "us_multi_frame_grayscale",
        "us_multi_frame_grayscale": TEST_DCM_ROOT / "us_multi_frame_grayscale",
    }


def collect_import_paths(*keys: str) -> list[str]:
    """Flatten DICOM file paths from named fixture directories."""
    dirs = fixture_dirs()
    paths: list[str] = []
    for key in keys:
        root = dirs.get(key) or (TEST_DCM_ROOT / key)
        if not root.is_dir():
            raise FileNotFoundError(f"Test DICOM fixture missing: {root}")
        paths.extend(list_import_directory_files(root))
    if not paths:
        raise FileNotFoundError(f"No DICOM files for fixtures: {keys}")
    return paths


def find_series_dirs(images_dir: Path) -> list[Path]:
    """Return leaf series directories under the public images tree."""
    series: list[Path] = []
    if not images_dir.is_dir():
        return series
    for patient in sorted(images_dir.iterdir()):
        if not patient.is_dir() or patient.name.startswith("."):
            continue
        for study in sorted(patient.iterdir()):
            if not study.is_dir() or study.name.startswith("."):
                continue
            for ser in sorted(study.iterdir()):
                if not ser.is_dir() or ser.name.startswith("."):
                    continue
                if any(ser.glob("*.dcm")):
                    series.append(ser)
    return series


def study_tuples(images_dir: Path) -> list[tuple[str, str]]:
    """(anon_patient_id, anon_study_uid) pairs for AI batch options."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for series in find_series_dirs(images_dir):
        study = series.parent
        patient = study.parent
        key = (patient.name, study.name)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def series_for_fixture(images_dir: Path, fixture_key: str) -> Path | None:
    """
    Best-effort match of an imported series to a fixture.

    After anonymization, folder names are UIDs — prefer modality/description
    heuristics and import order (most recently imported leaf).
    """
    series_dirs = find_series_dirs(images_dir)
    if not series_dirs:
        return None
    key = fixture_key.lower()
    if "davidson" in key or key == "cxr":
        from pydicom import dcmread

        for ser in series_dirs:
            dcms = list(ser.glob("*.dcm"))
            if not dcms:
                continue
            try:
                ds = dcmread(dcms[0], stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(ds, "Modality", "") or "").upper() in {"CR", "DX"}:
                return ser
        return series_dirs[0]
    if "brain" in key or "earlyart" in key or "ct_head" in key or "with_contrast" in key:
        from pydicom import dcmread

        ct_dirs: list[Path] = []
        for ser in series_dirs:
            dcms = list(ser.glob("*.dcm"))
            if not dcms:
                continue
            try:
                ds = dcmread(dcms[0], stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(ds, "Modality", "") or "").upper() in {"CT", "MR"}:
                ct_dirs.append(ser)
        pool = ct_dirs or series_dirs
        return max(pool, key=lambda p: len(list(p.glob("*.dcm"))))
    if key in {"us_mf", "us_multi_frame_grayscale"} or "multi_frame" in key:
        # Prefer multi-frame US (cine / lower-right panel demo).
        from pydicom import dcmread

        for ser in reversed(series_dirs):
            dcms = list(ser.glob("*.dcm"))
            if not dcms:
                continue
            try:
                ds = dcmread(dcms[0], stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(ds, "Modality", "") or "").upper() != "US":
                continue
            n_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
            if n_frames > 1 or len(dcms) > 1:
                return ser
        return series_dirs[-1]
    if key in {"us", "us_rgb_single_frame"} or "us_rgb" in key:
        # Prefer single-frame US (RGB abdomen / Dist panel demo).
        from pydicom import dcmread

        for ser in reversed(series_dirs):
            dcms = list(ser.glob("*.dcm"))
            if not dcms:
                continue
            try:
                ds = dcmread(dcms[0], stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(ds, "Modality", "") or "").upper() != "US":
                continue
            n_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
            if n_frames <= 1 and len(dcms) == 1:
                return ser
        for ser in reversed(series_dirs):
            dcms = list(ser.glob("*.dcm"))
            if not dcms:
                continue
            try:
                ds = dcmread(dcms[0], stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(ds, "Modality", "") or "").upper() == "US":
                return ser
        return series_dirs[-1]
    return series_dirs[-1]


def pick_series_for_modality(images_dir: Path, *needles: str) -> Path | None:
    series_dirs = find_series_dirs(images_dir)
    lowered = [n.lower() for n in needles if n]
    for ser in series_dirs:
        blob = str(ser).lower()
        if any(n in blob for n in lowered):
            return ser
    return series_dirs[0] if series_dirs else None
