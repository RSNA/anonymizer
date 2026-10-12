"""Download / probe / remove CXp projection+rotation weights under assets/ai/cxp_view."""

from __future__ import annotations

import logging
import shutil
from enum import StrEnum
from pathlib import Path

import requests

from anonymizer.utils.storage import update_model_download
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

CXP_VIEW_DIR = Path("assets/ai/cxp_view")
CXP_VIEW_WEIGHT_NAME = "cxp_projection_rotation.pt"
CXP_VIEW_WEIGHT_PATH = CXP_VIEW_DIR / CXP_VIEW_WEIGHT_NAME
CXP_VIEW_PARAMS_PATH = CXP_VIEW_DIR / "parameters.json"

_HF_SPACE = "MedicalAILabo/CXp-Projection-Rotation-Mislabel-Checker"
_HF_BASE = f"https://huggingface.co/spaces/{_HF_SPACE}/resolve/main"
_WEIGHT_URL = f"{_HF_BASE}/{CXP_VIEW_WEIGHT_NAME}"
_PARAMS_URL = f"{_HF_BASE}/parameters.json"

DOWNLOAD_ID = "harmonize_cxr_view"

_downloading = False


class CxpViewModelStatus(StrEnum):
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


def probe_cxp_view_models() -> tuple[CxpViewModelStatus, str]:
    if _downloading:
        return CxpViewModelStatus.DOWNLOADING, _("Downloading XR chest view model…")
    if not CXP_VIEW_WEIGHT_PATH.is_file():
        return CxpViewModelStatus.MISSING, _("Not downloaded")
    if CXP_VIEW_WEIGHT_PATH.stat().st_size < 1_000_000:
        return CxpViewModelStatus.FAILED, _("Download incomplete")
    return CxpViewModelStatus.READY, _("Downloaded")


def cxp_view_ready() -> bool:
    return probe_cxp_view_models()[0] == CxpViewModelStatus.READY


def _download_file(url: str, dest: Path, *, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    update_model_download(DOWNLOAD_ID, message=_("Downloading {label}…").format(label=label))
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if total > 0:
                    update_model_download(
                        DOWNLOAD_ID,
                        message=_("Downloading {label}…").format(label=label),
                        fraction=min(0.99, written / total),
                    )
    partial.replace(dest)


def download_cxp_view_models(*, verbose: bool = False) -> tuple[bool, str]:
    """Download CXp projection+rotation weights into assets/ai/cxp_view."""
    del verbose
    global _downloading
    status, _detail = probe_cxp_view_models()
    if status == CxpViewModelStatus.READY:
        logger.info("CXp view models already at %s", CXP_VIEW_DIR)
        return True, _("XR chest view model already downloaded.")

    _downloading = True
    try:
        CXP_VIEW_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading CXp view weights to %s", CXP_VIEW_DIR)
        update_model_download(
            DOWNLOAD_ID,
            message=_("Downloading XR chest view model to {path}").format(path=CXP_VIEW_DIR),
        )
        _download_file(_WEIGHT_URL, CXP_VIEW_WEIGHT_PATH, label=CXP_VIEW_WEIGHT_NAME)
        try:
            _download_file(_PARAMS_URL, CXP_VIEW_PARAMS_PATH, label="parameters.json")
        except Exception:
            logger.warning("Optional CXp parameters.json download failed", exc_info=True)
        from anonymizer.controller.ai.harmonize.cxp_view.predict import clear_model_cache

        clear_model_cache()
        # Clear before probe so READY is visible (probe treats _downloading as DOWNLOADING).
        _downloading = False
        status, detail = probe_cxp_view_models()
        if status == CxpViewModelStatus.READY:
            logger.info("CXp view models ready at %s", CXP_VIEW_DIR)
            return True, _("XR chest view model downloaded.")
        return False, detail or _("XR chest view download incomplete.")
    except Exception as exc:
        logger.exception("CXp view download failed")
        return False, str(exc)
    finally:
        _downloading = False


def remove_cxp_view_models() -> None:
    from anonymizer.controller.ai.harmonize.cxp_view.predict import clear_model_cache

    if CXP_VIEW_DIR.is_dir():
        shutil.rmtree(CXP_VIEW_DIR)
    CXP_VIEW_DIR.mkdir(parents=True, exist_ok=True)
    clear_model_cache()
    logger.info("Removed CXp view models from %s", CXP_VIEW_DIR)
