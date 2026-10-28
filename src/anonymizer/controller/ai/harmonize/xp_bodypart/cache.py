"""Download / probe / remove XR body-part weights under assets/ai/xp_bodypart.

Public API
----------
XP_BODYPART_DIR
    Xp bodypart dir.

XP_BODYPART_WEIGHT_NAME
    Xp bodypart weight name (default 'xp_bodypart.pt').

XP_BODYPART_WEIGHT_PATH
    Xp bodypart weight path.

XP_BODYPART_PARAMS_PATH
    Xp bodypart params path.

DOWNLOAD_ID
    Download id.

MODEL_SLOT
    Model slot.

clear_model_cache() -> None
    Drop in-memory weights (after remove/download).

XpBodypartModelStatus
    XpBodypartModelStatus type.

probe_xp_bodypart_models() -> tuple[XpBodypartModelStatus, str]
    Return cache status under assets/ai/xp_bodypart.

xp_bodypart_ready() -> bool
    Xp bodypart ready.

download_xp_bodypart_models(*, verbose: bool=False) -> tuple[bool, str]
    Download Xp-Bodypart-Checker weights into assets/ai/xp_bodypart.

remove_xp_bodypart_models() -> None
    Delete cached Xp bodypart weights.
"""
import logging
import shutil
from enum import StrEnum
from pathlib import Path

import requests

from anonymizer.controller.ai.feature_ids import DOWNLOAD_ID_HARMONIZE_XR_BODYPART
from anonymizer.controller.ai.harmonize.model_slot import ModelSlot
from anonymizer.controller.ai.model_download import update_model_download
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

XP_BODYPART_DIR = Path("assets/ai/xp_bodypart")
XP_BODYPART_WEIGHT_NAME = "xp_bodypart.pt"
XP_BODYPART_WEIGHT_PATH = XP_BODYPART_DIR / XP_BODYPART_WEIGHT_NAME
XP_BODYPART_PARAMS_PATH = XP_BODYPART_DIR / "parameters.json"

# Hugging Face Space (MedicalAILabo/Xp-Bodypart-Mislabel-Checker) — runtime download only.
_HF_SPACE = "MedicalAILabo/Xp-Bodypart-Mislabel-Checker"
_HF_BASE = f"https://huggingface.co/spaces/{_HF_SPACE}/resolve/main"
_WEIGHT_URL = f"{_HF_BASE}/{XP_BODYPART_WEIGHT_NAME}"
_PARAMS_URL = f"{_HF_BASE}/parameters.json"

DOWNLOAD_ID = DOWNLOAD_ID_HARMONIZE_XR_BODYPART

_downloading = False

# Loaded weights live here (not in predict) so download/remove can clear without importing inference.
MODEL_SLOT: ModelSlot = ModelSlot(label="Xp bodypart")


def clear_model_cache() -> None:
    """Drop in-memory weights (after remove/download)."""
    MODEL_SLOT.clear()


class XpBodypartModelStatus(StrEnum):
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


def probe_xp_bodypart_models() -> tuple[XpBodypartModelStatus, str]:
    """Return cache status under assets/ai/xp_bodypart."""
    if _downloading:
        return XpBodypartModelStatus.DOWNLOADING, _("Downloading XR body-part model…")
    if not XP_BODYPART_WEIGHT_PATH.is_file():
        return XpBodypartModelStatus.MISSING, _("Not downloaded")
    size = XP_BODYPART_WEIGHT_PATH.stat().st_size
    if size < 1_000_000:
        return XpBodypartModelStatus.FAILED, _("Download incomplete")
    return XpBodypartModelStatus.READY, _("Downloaded")


def xp_bodypart_ready() -> bool:
    return probe_xp_bodypart_models()[0] == XpBodypartModelStatus.READY


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


def download_xp_bodypart_models(*, verbose: bool = False) -> tuple[bool, str]:
    """Download Xp-Bodypart-Checker weights into assets/ai/xp_bodypart."""
    del verbose  # reserved for CLI parity with OCR download
    global _downloading
    status, _detail = probe_xp_bodypart_models()
    if status == XpBodypartModelStatus.READY:
        logger.info("Xp bodypart models already at %s", XP_BODYPART_DIR)
        return True, _("XR body-part model already downloaded.")

    _downloading = True
    try:
        XP_BODYPART_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading Xp bodypart weights to %s", XP_BODYPART_DIR)
        update_model_download(
            DOWNLOAD_ID,
            message=_("Downloading XR body-part model to {path}").format(path=XP_BODYPART_DIR),
        )
        _download_file(_WEIGHT_URL, XP_BODYPART_WEIGHT_PATH, label=XP_BODYPART_WEIGHT_NAME)
        try:
            _download_file(_PARAMS_URL, XP_BODYPART_PARAMS_PATH, label="parameters.json")
        except Exception:
            logger.warning("Optional parameters.json download failed", exc_info=True)

        clear_model_cache()
        status, detail = probe_xp_bodypart_models()
        if status == XpBodypartModelStatus.READY:
            logger.info("Xp bodypart models ready at %s", XP_BODYPART_DIR)
            return True, _("XR body-part model downloaded.")
        return False, detail or _("XR body-part download incomplete.")
    except Exception as exc:
        logger.exception("Xp bodypart download failed")
        return False, str(exc)
    finally:
        _downloading = False


def remove_xp_bodypart_models() -> None:
    """Delete cached Xp bodypart weights."""

    if XP_BODYPART_DIR.is_dir():
        shutil.rmtree(XP_BODYPART_DIR)
    XP_BODYPART_DIR.mkdir(parents=True, exist_ok=True)
    clear_model_cache()
    logger.info("Removed Xp bodypart models from %s", XP_BODYPART_DIR)
