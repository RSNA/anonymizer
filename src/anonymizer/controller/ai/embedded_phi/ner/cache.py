"""OpenMed DeID model cache: download, probe, load, and remove weights.
Weights live under assets/ai/embedded_phi/model (override via
NerModelOptions.cache_dir). Repo: OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1.

Public API
----------
HF_REPO_ID
    Hf repo id.

MODEL_DIR
    Model dir.

DOWNLOAD_ID
    Download id (default 'embedded_phi').

NerModelOptions
    Overrides for PHI NER weight resolution and Hugging Face load mode.

NerModelStatus
    Coarse status of the on-disk PHI NER model cache.

ner_ready(*, options: NerModelOptions | None=None) -> bool
    Return whether NER weights are ready for inference.

probe_ner_models(*, options: NerModelOptions | None=None) -> tuple[NerModelStatus, str]
    Probe download / readiness state for UI messaging.

download_ner_models(*, locale: str='en_US', options: NerModelOptions | None=None) -> tuple[bool, str]
    Download PHI NER models into the product cache if missing.

remove_ner_models(*, options: NerModelOptions | None=None) -> None
    Delete the on-disk NER model cache and recreate an empty cache directory.

load_token_classification_pipeline(model_id: str, *, options: NerModelOptions | None=None)
    Build a Hugging Face token-classification pipeline for model_id.

resolve_model_id(_locale: str='en_US', *, options: NerModelOptions | None=None) -> str
    Prefer a local cache directory when present; else the HF repo id.
"""
import logging
import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from huggingface_hub import snapshot_download
from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

from anonymizer.controller.ai.model_download import update_model_download
from anonymizer.utils.translate import _

try:
    import torch  # noqa: F401
except ImportError:
    torch = None  # type: ignore[assignment,misc]
try:
    import transformers  # noqa: F401
except ImportError:
    transformers = None  # type: ignore[assignment,misc]
logger = logging.getLogger(__name__)

HF_REPO_ID = "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1"
MODEL_DIR = Path("assets/ai/embedded_phi/model")
_MIN_MODEL_FILES = 3
DOWNLOAD_ID = "embedded_phi"
_downloading = False


@dataclass(frozen=True)
class NerModelOptions:
    """Overrides for PHI NER weight resolution and Hugging Face load mode."""

    model_id: str | None = None
    cache_dir: Path | None = None
    local_files_only: bool = False


class NerModelStatus(StrEnum):
    """Coarse status of the on-disk PHI NER model cache."""

    READY = "ready"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ner_ready(*, options: NerModelOptions | None = None) -> bool:
    """
    Return whether NER weights are ready for inference.

    Returns:
        True when probe_ner_models() reports READY.
    """
    return probe_ner_models(options=options)[0] == NerModelStatus.READY


def probe_ner_models(*, options: NerModelOptions | None = None) -> tuple[NerModelStatus, str]:
    """
    Probe download / readiness state for UI messaging.

    Returns:
        (status, localized_message).
    """
    if _downloading:
        return NerModelStatus.DOWNLOADING, _("Downloading PHI NER models…")
    if not _transformers_available():
        return NerModelStatus.FAILED, _("transformers/torch not installed")
    if _model_files_present(options):
        return NerModelStatus.READY, _("Downloaded")
    return NerModelStatus.MISSING, _("Not downloaded")


def download_ner_models(
    *, locale: str = "en_US", options: NerModelOptions | None = None
) -> tuple[bool, str]:
    """
    Download PHI NER models into the product cache if missing.

    Args:
        locale: Passed through to the pin helper (reserved for future packs).
        options: Optional model/cache overrides.

    Returns:
        (ok, localized_or_error_message).
    """
    global _downloading
    if not _transformers_available():
        return False, _("transformers/torch not installed")
    if _model_files_present(options):
        return True, _("PHI NER models already downloaded.")
    _downloading = True
    try:
        update_model_download(DOWNLOAD_ID, message=_("Downloading PHI NER model…"))
        _pin_deid_model(locale, options=options)
        if _model_files_present(options):
            return True, _("PHI NER models downloaded.")
        return False, _("PHI NER model download incomplete.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("PHI NER model download failed")
        return False, str(exc)
    finally:
        _downloading = False


def remove_ner_models(*, options: NerModelOptions | None = None) -> None:
    """
    Delete the on-disk NER model cache and recreate an empty cache directory.

    Returns:
        None.
    """
    cache = _model_cache_dir(options)
    if cache.is_dir():
        shutil.rmtree(cache)
    cache.mkdir(parents=True, exist_ok=True)
    logger.info("Removed PHI NER models from %s (%s)", cache, HF_REPO_ID)


def load_token_classification_pipeline(
    model_id: str, *, options: NerModelOptions | None = None
):
    """
    Build a Hugging Face token-classification pipeline for model_id.

    Args:
        model_id: Local directory or Hugging Face repo id.
        options: Optional load-mode overrides (local_files_only).

    Returns:
        transformers pipeline with aggregation_strategy="max" and no
        custom score threshold (HF default keeps all aggregated spans).
        The model is used exactly as published: no output classes are
        suppressed or otherwise adjusted.
    """
    opts = _resolve_options(options)
    lfo = opts.local_files_only
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=lfo)
    model = AutoModelForTokenClassification.from_pretrained(model_id, local_files_only=lfo)
    # OpenMed labels every WordPiece as B-* (never I-*), so "simple" never merges
    # subwords. "max"/"first"/"average" group consecutive same-entity tokens into
    # whole words (Mnikathi, not Mn/ika/thi). No threshold — scores are logged
    # only; product labels are not filtered by confidence.
    return pipeline(
        "token-classification",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy="max",
    )


def resolve_model_id(
    _locale: str = "en_US", *, options: NerModelOptions | None = None
) -> str:
    """
    Prefer a local cache directory when present; else the HF repo id.

    Args:
        _locale: Reserved for future locale-specific packs (currently unused).
        options: Optional model/cache overrides.

    Returns:
        Filesystem path string, options.model_id, or HF_REPO_ID.
    """
    opts = _resolve_options(options)
    if opts.model_id:
        return opts.model_id
    cache = _model_cache_dir(opts)
    if cache.is_dir() and (cache / "config.json").is_file():
        return str(cache)
    nested = cache / HF_REPO_ID.replace("/", "__")
    if nested.is_dir() and (nested / "config.json").is_file():
        return str(nested)
    return HF_REPO_ID


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_options(options: NerModelOptions | None) -> NerModelOptions:
    return options if options is not None else NerModelOptions()


def _model_cache_dir(options: NerModelOptions | None = None) -> Path:
    """
    Resolve the directory used for OpenMed DeID weights.

    Returns:
        options.cache_dir when set, otherwise the packaged MODEL_DIR.
    """
    opts = _resolve_options(options)
    return Path(opts.cache_dir).expanduser() if opts.cache_dir is not None else MODEL_DIR


def _pin_deid_model(
    locale: str = "en_US", *, options: NerModelOptions | None = None
) -> Path:
    """
    Download the DeID model into the product cache.

    Args:
        locale: Reserved for future locale-specific packs (currently unused).
        options: Optional cache-directory override.

    Returns:
        Cache directory path after snapshot download.
    """

    del locale
    dest = _model_cache_dir(options)
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=HF_REPO_ID, local_dir=str(dest))
    logger.info("Pinned Embedded PHI DeID model → %s", dest)
    return dest


def _model_files_present(options: NerModelOptions | None = None) -> bool:
    """
    Return whether the cache looks like a complete model tree.

    Returns:
        True when config.json exists and enough non-dot files are present.
    """
    cache = _model_cache_dir(options)
    if not cache.is_dir():
        return False
    try:
        names = [n for n in os.listdir(cache) if not n.startswith(".")]
    except OSError:
        return False
    return len(names) >= _MIN_MODEL_FILES and (cache / "config.json").is_file()


def _transformers_available() -> bool:
    """
    Return whether torch and transformers can be imported.

    Returns:
        True when both packages import successfully.
    """
    return torch is not None and transformers is not None
