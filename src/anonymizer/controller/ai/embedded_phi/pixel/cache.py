"""Download / probe / remove EasyOCR weights under ``assets/ai/ocr/model``."""

from __future__ import annotations

import logging
import os
import shutil
from enum import StrEnum

from easyocr import Reader

from anonymizer.utils.network import ensure_ssl_certifi
from anonymizer.utils.package_paths import ai_feature_dir
from anonymizer.utils.storage import update_model_download
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

OCR_MODEL_DIR = ai_feature_dir("ocr", "model")
OCR_LANGS = ("en", "de", "fr", "es")
_MIN_OCR_MODEL_FILES = 2
DOWNLOAD_ID = "embedded_phi"
_ocr_downloading = False


class OcrModelStatus(StrEnum):
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


def _ocr_model_files_present() -> bool:
    """True when the EasyOCR cache directory has enough weight files (ignores download latch)."""
    if not OCR_MODEL_DIR.is_dir():
        return False
    try:
        models = [name for name in os.listdir(OCR_MODEL_DIR) if not name.startswith(".")]
    except OSError:
        return False
    return len(models) >= _MIN_OCR_MODEL_FILES


def probe_ocr_models() -> tuple[OcrModelStatus, str]:
    """Return OCR model cache status under assets/ai/ocr/model."""
    if _ocr_downloading:
        return OcrModelStatus.DOWNLOADING, _("Downloading OCR models…")
    if not _ocr_model_files_present():
        return OcrModelStatus.MISSING, _("Not downloaded")
    return OcrModelStatus.READY, _("Downloaded")


def download_ocr_models(*, verbose: bool = False) -> tuple[bool, str]:
    """Download EasyOCR weights into assets/ai/ocr/model."""
    global _ocr_downloading

    ensure_ssl_certifi()
    OCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if _ocr_model_files_present():
        logger.info("OCR models already downloaded at %s", OCR_MODEL_DIR)
        return True, _("OCR models already downloaded.")
    _ocr_downloading = True
    start_message = _("Downloading OCR models to {path}").format(path=OCR_MODEL_DIR)
    try:
        logger.info("Downloading OCR models to %s", OCR_MODEL_DIR)
        update_model_download(DOWNLOAD_ID, message=start_message)
        update_model_download(DOWNLOAD_ID, message=_("Downloading OCR language models…"))
        Reader(
            lang_list=list(OCR_LANGS),
            model_storage_directory=str(OCR_MODEL_DIR),
            verbose=verbose,
        )
        # Do not call probe_ocr_models() here: the download latch would report DOWNLOADING.
        if _ocr_model_files_present():
            logger.info("OCR models downloaded to %s", OCR_MODEL_DIR)
            return True, _("OCR models downloaded.")
        return False, _("OCR model download incomplete.")
    except Exception as exc:
        logger.exception("OCR model download failed")
        return False, str(exc)
    finally:
        _ocr_downloading = False


def ocr_models_ready() -> bool:
    return _ocr_model_files_present() and not _ocr_downloading


def remove_ocr_models() -> None:
    """Delete cached EasyOCR weights under assets/ai/ocr/model."""
    if OCR_MODEL_DIR.is_dir():
        shutil.rmtree(OCR_MODEL_DIR)
    OCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Removed OCR models from %s", OCR_MODEL_DIR)
