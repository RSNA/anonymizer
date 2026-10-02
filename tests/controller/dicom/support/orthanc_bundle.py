"""Download, configure, start, and stop a managed Orthanc instance for dicom_integration tests."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import requests

from anonymizer.model.project import DICOMNode

logger = logging.getLogger(__name__)

ORTHANC_VERSION = "1.12.7"
DICOMWEB_PLUGIN_VERSION = "1.18"
GDCM_PLUGIN_VERSION = "1.8"

DICOM_PORT = 11242
HTTP_PORT = 18042
ORTHANC_AET = "ORTHANC"
ORTHANC_USER = "test"
ORTHANC_PASSWORD = "test"

SUPPORT_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = SUPPORT_DIR / "orthanc_runtime"

_DOWNLOAD_BASE = "https://orthanc.uclouvain.be/downloads"


@dataclass(frozen=True)
class ManagedOrthanc:
    """Running Orthanc process and remotes for DIMSE / DICOMweb."""

    process: subprocess.Popen
    runtime_dir: Path
    dimse: DICOMNode
    dicomweb: DICOMNode


class OrthancBundleError(RuntimeError):
    """Fatal Orthanc lifecycle failure (hard-fail in CI)."""


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return "macos"
    if system == "linux" and machine in ("x86_64", "amd64"):
        return "linux_x86_64"
    raise OrthancBundleError(f"Unsupported platform for managed Orthanc: {system}/{machine}")


def _artifact_urls(plat: str) -> dict[str, tuple[str, str]]:
    """Map local filename → download URL for Orthanc core + plugins."""
    if plat == "macos":
        return {
            "Orthanc": f"{_DOWNLOAD_BASE}/macos/orthanc/{ORTHANC_VERSION}/Orthanc",
            f"OrthancDicomWeb-{DICOMWEB_PLUGIN_VERSION}.dylib": (
                f"{_DOWNLOAD_BASE}/macos/orthanc-dicomweb/OrthancDicomWeb-{DICOMWEB_PLUGIN_VERSION}.dylib"
            ),
            f"OrthancGdcm-{GDCM_PLUGIN_VERSION}.dylib": (
                f"{_DOWNLOAD_BASE}/macos/orthanc-gdcm/OrthancGdcm-{GDCM_PLUGIN_VERSION}.dylib"
            ),
        }
    if plat == "linux_x86_64":
        return {
            "Orthanc": f"{_DOWNLOAD_BASE}/linux-standard-base/orthanc/{ORTHANC_VERSION}/Orthanc",
            "libOrthancDicomWeb.so": (
                f"{_DOWNLOAD_BASE}/linux-standard-base/orthanc-dicomweb/"
                f"{DICOMWEB_PLUGIN_VERSION}/libOrthancDicomWeb.so"
            ),
            "libOrthancGdcm.so": (
                f"{_DOWNLOAD_BASE}/linux-standard-base/orthanc-gdcm/{GDCM_PLUGIN_VERSION}/libOrthancGdcm.so"
            ),
        }
    raise OrthancBundleError(f"No Orthanc download URLs for {plat}")


def _plugin_filenames(plat: str) -> list[str]:
    return [name for name in _artifact_urls(plat) if name != "Orthanc"]


def runtime_dir_for_platform(plat: str | None = None) -> Path:
    return RUNTIME_ROOT / (plat or _platform_key())


def storage_dir(runtime: Path) -> Path:
    return runtime / "storage"


def config_path(runtime: Path) -> Path:
    return runtime / "config.json"


def _download_file(url: str, dest: Path, *, timeout: float = 120.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    logger.info("Downloading %s → %s", url, dest)
    try:
        with urlopen(url, timeout=timeout) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
    except (URLError, OSError, TimeoutError) as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise OrthancBundleError(f"Failed to download {url}: {exc}") from exc
    tmp.replace(dest)


def ensure_bundle(runtime: Path | None = None) -> Path:
    """Download Orthanc + plugins into runtime dir if missing. Returns runtime dir."""
    plat = _platform_key()
    runtime = runtime or runtime_dir_for_platform(plat)
    runtime.mkdir(parents=True, exist_ok=True)

    artifacts = _artifact_urls(plat)
    for name, url in artifacts.items():
        dest = runtime / name
        min_size = 1_000_000 if name == "Orthanc" else 100_000
        if not dest.is_file() or dest.stat().st_size < min_size:
            _download_file(url, dest)
        if name == "Orthanc":
            dest.chmod(dest.stat().st_mode | 0o111)
    return runtime


def write_config(runtime: Path, *, scp_port: int = 1045, scp_aet: str = "ANONYMIZER") -> Path:
    """Write Orthanc config for managed ports / DICOMweb / test auth."""
    plat = _platform_key()
    plugin_paths = [str((runtime / name).resolve()) for name in _plugin_filenames(plat)]
    store = storage_dir(runtime)
    store.mkdir(parents=True, exist_ok=True)

    cfg = {
        "Name": "AnonymizerTestOrthanc",
        "StorageDirectory": str(store.resolve()),
        "IndexDirectory": str(store.resolve()),
        "StorageCompression": False,
        "HttpServerEnabled": True,
        "HttpPort": HTTP_PORT,
        "HttpDescribeErrors": True,
        "RemoteAccessAllowed": True,
        "AuthenticationEnabled": True,
        "RegisteredUsers": {ORTHANC_USER: ORTHANC_PASSWORD},
        "SslEnabled": False,
        "DicomServerEnabled": True,
        "DicomAet": ORTHANC_AET,
        "DicomCheckCalledAet": False,
        "DicomPort": DICOM_PORT,
        "DefaultEncoding": "Latin1",
        "UnknownSopClassAccepted": True,
        "AcceptedTransferSyntaxes": ["1.2.840.10008.1.*"],
        "Plugins": plugin_paths,
        "Gdcm": {
            "Throttling": 4,
            "RestrictTransferSyntaxes": [
                "1.2.840.10008.1.2.4.90",
                "1.2.840.10008.1.2.4.91",
            ],
        },
        "DicomWeb": {
            "Enable": True,
            "Root": "/dicom-web/",
            "EnableWado": True,
            "WadoRoot": "/wado",
            "Ssl": False,
            "QidoCaseSensitive": False,
            "Host": f"127.0.0.1:{HTTP_PORT}",
            "StudiesMetadata": "Full",
            "SeriesMetadata": "Full",
            "PublicRoot": "/dicom-web/",
        },
        "DicomModalities": {
            scp_aet: [scp_aet, "127.0.0.1", scp_port],
        },
        "StableAge": 1,
        "StrictAetComparison": False,
        "StoreMD5ForAttachments": False,
        "LimitFindResults": 0,
        "LimitFindInstances": 0,
        "JobsHistorySize": 10,
        "StoreDicom": True,
        "DicomAssociationCloseDelay": 5,
        "QueryRetrieveSize": 10,
        "CaseSensitivePN": False,
        "StorageAccessOnFind": "Always",
    }
    path = config_path(runtime)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def dicomweb_healthy(timeout: float = 2.0) -> bool:
    url = f"http://127.0.0.1:{HTTP_PORT}/dicom-web/studies"
    try:
        resp = requests.get(
            url,
            auth=(ORTHANC_USER, ORTHANC_PASSWORD),
            timeout=timeout,
            headers={"Accept": "application/dicom+json"},
        )
    except requests.RequestException:
        return False
    return resp.status_code in (200, 204)


def wait_until_ready(*, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open("127.0.0.1", DICOM_PORT) and dicomweb_healthy():
            return
        time.sleep(0.25)
    raise OrthancBundleError(
        f"Orthanc did not become ready on DICOM {DICOM_PORT} / HTTP {HTTP_PORT} within {timeout}s"
    )


def wipe_storage(runtime: Path) -> None:
    store = storage_dir(runtime)
    if store.exists():
        shutil.rmtree(store)
    store.mkdir(parents=True, exist_ok=True)


def wipe_patients_via_rest(*, timeout: float = 10.0) -> None:
    """Delete all patients via Orthanc REST (test isolation between cases)."""
    base = f"http://127.0.0.1:{HTTP_PORT}"
    auth = (ORTHANC_USER, ORTHANC_PASSWORD)
    try:
        patients = requests.get(f"{base}/patients", auth=auth, timeout=timeout)
        patients.raise_for_status()
        for pid in patients.json():
            requests.delete(f"{base}/patients/{pid}", auth=auth, timeout=timeout)
    except requests.RequestException as exc:
        raise OrthancBundleError(f"Failed to wipe Orthanc patients: {exc}") from exc


def make_nodes() -> tuple[DICOMNode, DICOMNode]:
    dimse = DICOMNode("127.0.0.1", DICOM_PORT, ORTHANC_AET, False)
    dicomweb = DICOMNode(
        "127.0.0.1",
        DICOM_PORT,
        ORTHANC_AET,
        False,
        dicomweb=True,
        http_port=HTTP_PORT,
        http_path="/dicom-web",
        use_https=False,
        username=ORTHANC_USER,
        password=ORTHANC_PASSWORD,
    )
    return dimse, dicomweb


def start_orthanc(
    *,
    scp_port: int = 1045,
    scp_aet: str = "ANONYMIZER",
    wipe: bool = True,
) -> ManagedOrthanc:
    """Ensure bundle, write config, start Orthanc, wait until healthy."""
    runtime = ensure_bundle()
    if wipe:
        wipe_storage(runtime)
    cfg = write_config(runtime, scp_port=scp_port, scp_aet=scp_aet)
    orthanc_bin = runtime / "Orthanc"
    log_path = runtime / "orthanc.log"
    log_file = open(log_path, "wb")  # noqa: SIM115 — kept open for process lifetime
    try:
        proc = subprocess.Popen(
            [str(orthanc_bin), str(cfg)],
            cwd=str(runtime),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        log_file.close()
        raise OrthancBundleError(f"Failed to start Orthanc: {exc}") from exc

    try:
        wait_until_ready(timeout=90.0)
    except OrthancBundleError:
        stop_orthanc(proc)
        log_file.close()
        tail = ""
        if log_path.is_file():
            tail = log_path.read_text(errors="replace")[-2000:]
        raise OrthancBundleError(f"Orthanc failed to become ready. Log tail:\n{tail}") from None

    dimse, dicomweb = make_nodes()
    # Attach log handle so stop can close it
    proc._orthanc_log_file = log_file  # type: ignore[attr-defined]
    return ManagedOrthanc(process=proc, runtime_dir=runtime, dimse=dimse, dicomweb=dicomweb)


def stop_orthanc(proc: subprocess.Popen | ManagedOrthanc, *, timeout: float = 15.0) -> None:
    if isinstance(proc, ManagedOrthanc):
        process = proc.process
    else:
        process = proc
    log_file = getattr(process, "_orthanc_log_file", None)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log_file is not None:
        try:
            log_file.close()
        except Exception:
            pass


def in_ci() -> bool:
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")
