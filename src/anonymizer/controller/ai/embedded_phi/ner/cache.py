"""OpenMed DeID model cache: download, probe, load, and remove weights.

Weights live under ``assets/ai/embedded_phi/model`` (override with
``PHI_NER_MODEL_CACHE``). Repo: ``OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1``.

Public API
----------
``ner_ready()``
    True when weights are present and transformers/torch import.

``probe_ner_models()``
    ``(NerModelStatus, localized_message)`` for UI.

``download_ner_models(*, locale=\"en_US\")``
    Fetch weights into the product cache → ``(ok, message)``.

``remove_ner_models()``
    Delete the on-disk cache.

``load_token_classification_pipeline(model_id)``
    Build the HF token-classification pipeline (used by ``ner.detect_entities``).

``resolve_model_id(locale=\"en_US\")``
    Local cache path when present, else HF repo id.

``NerModelStatus``
    ``READY`` / ``MISSING`` / ``DOWNLOADING`` / ``FAILED``.
"""

from __future__ import annotations

import logging
import os
import shutil
from enum import StrEnum
from pathlib import Path

from anonymizer.utils.storage import update_model_download
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

HF_REPO_ID = "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1"
MODEL_DIR = Path(__file__).resolve().parents[4] / "assets" / "ai" / "embedded_phi" / "model"
_MIN_MODEL_FILES = 3
DOWNLOAD_ID = "embedded_phi"
_downloading = False


class NerModelStatus(StrEnum):
    """Coarse status of the on-disk PHI NER model cache."""

    READY = "ready"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ner_ready() -> bool:
    """
    Return whether NER weights are ready for inference.

    Returns:
        True when ``probe_ner_models()`` reports ``READY``.
    """
    return probe_ner_models()[0] == NerModelStatus.READY


def probe_ner_models() -> tuple[NerModelStatus, str]:
    """
    Probe download / readiness state for UI messaging.

    Returns:
        ``(status, localized_message)``.
    """
    if _downloading:
        return NerModelStatus.DOWNLOADING, _("Downloading PHI NER models…")
    if not _transformers_available():
        return NerModelStatus.FAILED, _("transformers/torch not installed")
    if _model_files_present():
        return NerModelStatus.READY, _("Downloaded")
    return NerModelStatus.MISSING, _("Not downloaded")


def download_ner_models(*, locale: str = "en_US") -> tuple[bool, str]:
    """
    Download PHI NER models into the product cache if missing.

    Args:
        locale: Passed through to the pin helper (reserved for future packs).

    Returns:
        ``(ok, localized_or_error_message)``.
    """
    global _downloading
    if not _transformers_available():
        return False, _("transformers/torch not installed")
    if _model_files_present():
        return True, _("PHI NER models already downloaded.")
    _downloading = True
    try:
        update_model_download(DOWNLOAD_ID, message=_("Downloading PHI NER model…"))
        _pin_deid_model(locale)
        if _model_files_present():
            return True, _("PHI NER models downloaded.")
        return False, _("PHI NER model download incomplete.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("PHI NER model download failed")
        return False, str(exc)
    finally:
        _downloading = False


def remove_ner_models() -> None:
    """
    Delete the on-disk NER model cache and recreate an empty cache directory.

    Returns:
        None.
    """
    cache = _model_cache_dir()
    if cache.is_dir():
        shutil.rmtree(cache)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Removed PHI NER models from %s (%s)", cache, HF_REPO_ID)


def load_token_classification_pipeline(model_id: str):
    """
    Build a Hugging Face token-classification pipeline for ``model_id``.

    Args:
        model_id: Local directory or Hugging Face repo id.

    Returns:
        ``transformers`` pipeline with ``aggregation_strategy=\"max\"`` and no
        custom score threshold (HF default keeps all aggregated spans).
    """
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        pipeline,
    )

    lfo = _local_files_only()
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=lfo)
    model = AutoModelForTokenClassification.from_pretrained(model_id, local_files_only=lfo)
    # OpenMed labels every WordPiece as B-* (never I-*), so "simple" never merges
    # subwords. "max"/"first"/"average" group consecutive same-entity tokens into
    # whole words (Mnikathi, not Mn/ika/thi). No ``threshold`` — scores are logged
    # only; product labels are not filtered by confidence.
    return pipeline(
        "token-classification",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy="max",
    )


def resolve_model_id(_locale: str = "en_US") -> str:
    """
    Prefer a local cache directory when present; else the HF repo id.

    Args:
        _locale: Reserved for future locale-specific packs (currently unused).

    Returns:
        Filesystem path string or ``HF_REPO_ID``.
    """
    override = os.environ.get("PHI_NER_DEID_MODEL", "").strip()
    if override:
        return override
    cache = _model_cache_dir()
    if cache.is_dir() and (cache / "config.json").is_file():
        return str(cache)
    nested = cache / HF_REPO_ID.replace("/", "__")
    if nested.is_dir() and (nested / "config.json").is_file():
        return str(nested)
    return HF_REPO_ID


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _model_cache_dir() -> Path:
    """
    Resolve the directory used for OpenMed DeID weights.

    Returns:
        ``PHI_NER_MODEL_CACHE`` when set, otherwise the packaged ``MODEL_DIR``.
    """
    raw = os.environ.get("PHI_NER_MODEL_CACHE", "").strip()
    return Path(raw).expanduser() if raw else MODEL_DIR


def _local_files_only() -> bool:
    """
    Return whether Hugging Face loads must use local files only.

    Returns:
        True when ``PHI_NER_LOCAL_FILES_ONLY`` is a truthy string.
    """
    return os.environ.get("PHI_NER_LOCAL_FILES_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _pin_deid_model(locale: str = "en_US") -> Path:
    """
    Download the DeID model into the product cache.

    Args:
        locale: Reserved for future locale-specific packs (currently unused).

    Returns:
        Cache directory path after snapshot download.
    """
    from huggingface_hub import snapshot_download

    del locale
    dest = _model_cache_dir()
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=HF_REPO_ID, local_dir=str(dest))
    logger.info("Pinned Embedded PHI DeID model → %s", dest)
    return dest


def _model_files_present() -> bool:
    """
    Return whether the cache looks like a complete model tree.

    Returns:
        True when ``config.json`` exists and enough non-dot files are present.
    """
    cache = _model_cache_dir()
    if not cache.is_dir():
        return False
    try:
        names = [n for n in os.listdir(cache) if not n.startswith(".")]
    except OSError:
        return False
    return len(names) >= _MIN_MODEL_FILES and (cache / "config.json").is_file()


def _transformers_available() -> bool:
    """
    Return whether ``torch`` and ``transformers`` can be imported.

    Returns:
        True when both packages import successfully.
    """
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True
