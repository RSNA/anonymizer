"""Download / probe / remove XR chest view weights under ``assets/ai/xr_chest_view``.

Upstream model: MedicalAILabo CXp-Projection-Rotation-Mislabel-Checker
(chest X-ray AP/PA/Lateral + rotation). Product name: **XR chest view**.
"""

from __future__ import annotations

import logging
import shutil
from enum import StrEnum
from pathlib import Path

import requests

from anonymizer.controller.ai.harmonize.model_slot import ModelSlot
from anonymizer.utils.package_paths import ai_feature_dir
from anonymizer.controller.ai.model_download import update_model_download
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

XR_CHEST_VIEW_DIR = ai_feature_dir("xr_chest_view")
# Upstream weight filename (HF Space); keep name for download URL compatibility.
XR_CHEST_VIEW_WEIGHT_NAME = "cxp_projection_rotation.pt"
XR_CHEST_VIEW_WEIGHT_PATH = XR_CHEST_VIEW_DIR / XR_CHEST_VIEW_WEIGHT_NAME
XR_CHEST_VIEW_PARAMS_PATH = XR_CHEST_VIEW_DIR / "parameters.json"

# Back-compat aliases (older imports / docs).
CXP_VIEW_DIR = XR_CHEST_VIEW_DIR
CXP_VIEW_WEIGHT_NAME = XR_CHEST_VIEW_WEIGHT_NAME
CXP_VIEW_WEIGHT_PATH = XR_CHEST_VIEW_WEIGHT_PATH
CXP_VIEW_PARAMS_PATH = XR_CHEST_VIEW_PARAMS_PATH

_HF_SPACE = "MedicalAILabo/CXp-Projection-Rotation-Mislabel-Checker"
_HF_BASE = f"https://huggingface.co/spaces/{_HF_SPACE}/resolve/main"
_WEIGHT_URL = f"{_HF_BASE}/{XR_CHEST_VIEW_WEIGHT_NAME}"
_PARAMS_URL = f"{_HF_BASE}/parameters.json"

DOWNLOAD_ID = "harmonize_cxr_view"

_downloading = False

# Loaded weights live here (not in ``predict``) so download/remove can clear without importing inference.
MODEL_SLOT: ModelSlot = ModelSlot(label="CXp view")


def clear_model_cache() -> None:
    """Drop in-memory weights (after remove/download)."""
    MODEL_SLOT.clear()


class XrChestViewModelStatus(StrEnum):
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


# Back-compat alias
CxpViewModelStatus = XrChestViewModelStatus


def probe_xr_chest_view_models() -> tuple[XrChestViewModelStatus, str]:
    if _downloading:
        return XrChestViewModelStatus.DOWNLOADING, _("Downloading XR chest view model…")
    if not XR_CHEST_VIEW_WEIGHT_PATH.is_file():
        return XrChestViewModelStatus.MISSING, _("Not downloaded")
    if XR_CHEST_VIEW_WEIGHT_PATH.stat().st_size < 1_000_000:
        return XrChestViewModelStatus.FAILED, _("Download incomplete")
    return XrChestViewModelStatus.READY, _("Downloaded")


def xr_chest_view_ready() -> bool:
    return probe_xr_chest_view_models()[0] == XrChestViewModelStatus.READY


probe_cxp_view_models = probe_xr_chest_view_models
cxp_view_ready = xr_chest_view_ready


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


def download_xr_chest_view_models(*, verbose: bool = False) -> tuple[bool, str]:
    """Download XR chest view weights into ``assets/ai/xr_chest_view``."""
    del verbose
    global _downloading
    status, _detail = probe_xr_chest_view_models()
    if status == XrChestViewModelStatus.READY:
        logger.info("XR chest view models already at %s", XR_CHEST_VIEW_DIR)
        return True, _("XR chest view model already downloaded.")

    _downloading = True
    try:
        XR_CHEST_VIEW_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading XR chest view weights to %s", XR_CHEST_VIEW_DIR)
        update_model_download(
            DOWNLOAD_ID,
            message=_("Downloading XR chest view model to {path}").format(path=XR_CHEST_VIEW_DIR),
        )
        _download_file(_WEIGHT_URL, XR_CHEST_VIEW_WEIGHT_PATH, label=XR_CHEST_VIEW_WEIGHT_NAME)
        try:
            _download_file(_PARAMS_URL, XR_CHEST_VIEW_PARAMS_PATH, label="parameters.json")
        except Exception:
            logger.warning("Optional XR chest view parameters.json download failed", exc_info=True)

        clear_model_cache()
        _downloading = False
        status, detail = probe_xr_chest_view_models()
        if status == XrChestViewModelStatus.READY:
            logger.info("XR chest view models ready at %s", XR_CHEST_VIEW_DIR)
            return True, _("XR chest view model downloaded.")
        return False, detail or _("XR chest view download incomplete.")
    except Exception as exc:
        logger.exception("XR chest view download failed")
        return False, str(exc)
    finally:
        _downloading = False


download_cxp_view_models = download_xr_chest_view_models


def remove_xr_chest_view_models() -> None:

    if XR_CHEST_VIEW_DIR.is_dir():
        shutil.rmtree(XR_CHEST_VIEW_DIR)
    XR_CHEST_VIEW_DIR.mkdir(parents=True, exist_ok=True)
    clear_model_cache()
    logger.info("Removed XR chest view models from %s", XR_CHEST_VIEW_DIR)


remove_cxp_view_models = remove_xr_chest_view_models
