"""Download / probe / remove OpenMed DeID weights under assets/ai/embedded_phi/model."""

from __future__ import annotations

import logging
import os
import shutil
from enum import StrEnum
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.ner.locale_registry import get_locale_pack
from anonymizer.utils.storage import update_model_download
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

HF_REPO_ID = "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1"
MODEL_DIR = Path(__file__).resolve().parents[4] / "assets" / "ai" / "embedded_phi" / "model"
_MIN_MODEL_FILES = 3
DOWNLOAD_ID = "embedded_phi"
_downloading = False


class NerModelStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    FAILED = "failed"


def model_cache_dir() -> Path:
    raw = os.environ.get("PHI_NER_MODEL_CACHE", "").strip()
    return Path(raw).expanduser() if raw else MODEL_DIR


def local_files_only() -> bool:
    return os.environ.get("PHI_NER_LOCAL_FILES_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def resolve_model_id(locale: str = "en_US") -> str:
    """Prefer local cache directory when present; else HF repo id."""
    override = os.environ.get("PHI_NER_DEID_MODEL", "").strip()
    if override:
        return override
    pack = get_locale_pack(locale)
    model_id = pack.hf_deid_model
    cache = model_cache_dir()
    if cache.is_dir() and (cache / "config.json").is_file():
        return str(cache)
    nested = cache / model_id.replace("/", "__")
    if nested.is_dir() and (nested / "config.json").is_file():
        return str(nested)
    return model_id


def load_token_classification_pipeline(model_id: str):
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        pipeline,
    )

    lfo = local_files_only()
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=lfo)
    model = AutoModelForTokenClassification.from_pretrained(model_id, local_files_only=lfo)
    # OpenMed labels every WordPiece as B-* (never I-*), so "simple" never merges
    # subwords. "max"/"first"/"average" group consecutive same-entity tokens into
    # whole words (Mnikathi, not Mn/ika/thi).
    return pipeline(
        "token-classification",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy="max",
    )


def pin_deid_model(locale: str = "en_US") -> Path:
    """Download model into the product cache. Returns cache path."""
    from huggingface_hub import snapshot_download

    pack = get_locale_pack(locale)
    dest = model_cache_dir()
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=pack.hf_deid_model, local_dir=str(dest))
    logger.info("Pinned Embedded PHI DeID model → %s", dest)
    return dest


def model_files_present() -> bool:
    cache = model_cache_dir()
    if not cache.is_dir():
        return False
    try:
        names = [n for n in os.listdir(cache) if not n.startswith(".")]
    except OSError:
        return False
    return len(names) >= _MIN_MODEL_FILES and (cache / "config.json").is_file()


def transformers_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


def probe_ner_models() -> tuple[NerModelStatus, str]:
    if _downloading:
        return NerModelStatus.DOWNLOADING, _("Downloading PHI NER models…")
    if not transformers_available():
        return NerModelStatus.FAILED, _("transformers/torch not installed")
    if model_files_present():
        return NerModelStatus.READY, _("Downloaded")
    return NerModelStatus.MISSING, _("Not downloaded")


def ner_ready() -> bool:
    return probe_ner_models()[0] == NerModelStatus.READY


def download_ner_models(*, locale: str = "en_US") -> tuple[bool, str]:
    global _downloading
    if not transformers_available():
        return False, _("transformers/torch not installed")
    if model_files_present():
        return True, _("PHI NER models already downloaded.")
    _downloading = True
    try:
        update_model_download(DOWNLOAD_ID, message=_("Downloading PHI NER model…"))
        pin_deid_model(locale)
        # model_files_present() ignores the download latch (unlike probe_ner_models).
        if model_files_present():
            return True, _("PHI NER models downloaded.")
        return False, _("PHI NER model download incomplete.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("PHI NER model download failed")
        return False, str(exc)
    finally:
        _downloading = False


def remove_ner_models() -> None:
    cache = model_cache_dir()
    if cache.is_dir():
        shutil.rmtree(cache)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Removed PHI NER models from %s (%s)", cache, HF_REPO_ID)
