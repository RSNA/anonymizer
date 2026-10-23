"""Offline pinning helpers for clinical DeID HuggingFace models."""

import os
from pathlib import Path

from prototyping.metadata_phi.locale_registry import get_locale_pack

# Default cache under the package (gitignored if large). Override with env.
_DEFAULT_CACHE = Path(__file__).resolve().parent / ".model_cache"


def model_cache_dir() -> Path:
    raw = os.environ.get("METADATA_PHI_MODEL_CACHE", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_CACHE


def local_files_only() -> bool:
    return os.environ.get("METADATA_PHI_LOCAL_FILES_ONLY", "").strip() in {"1", "true", "yes"}


def resolve_model_id(locale: str = "en_US", *, kind: str = "deid") -> str:
    """
    Resolve HF model id or local directory for DeID weights.

    Precedence:
      1. METADATA_PHI_DEID_MODEL / METADATA_PHI_LONGFORMER_MODEL env
      2. <cache>/<sanitized_model_id> if present
      3. Locale pack model id (download unless LOCAL_FILES_ONLY)
    """
    pack = get_locale_pack(locale)
    if kind == "longformer":
        env_key = "METADATA_PHI_LONGFORMER_MODEL"
        model_id = pack.hf_longformer_model
    else:
        env_key = "METADATA_PHI_DEID_MODEL"
        model_id = pack.hf_deid_model

    override = os.environ.get(env_key, "").strip()
    if override:
        return override

    cache = model_cache_dir() / model_id.replace("/", "__")
    if cache.is_dir() and any(cache.iterdir()):
        return str(cache)
    return model_id


def pin_deid_model(locale: str = "en_US", *, kind: str = "deid") -> Path:
    """Download model into the package cache for offline reuse. Returns cache path."""
    from huggingface_hub import snapshot_download

    pack = get_locale_pack(locale)
    model_id = pack.hf_longformer_model if kind == "longformer" else pack.hf_deid_model
    dest = model_cache_dir() / model_id.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_id, local_dir=str(dest))
    return dest


def load_token_classification_pipeline(model_id: str):
    """
    Build a HF token-classification pipeline.

    ``local_files_only`` must be applied at ``from_pretrained`` time — it is not a
    valid ``pipeline(...)`` kwarg on TokenClassificationPipeline.
    """
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        pipeline,
    )

    lfo = local_files_only()
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=lfo)
    model = AutoModelForTokenClassification.from_pretrained(
        model_id, local_files_only=lfo
    )
    return pipeline(
        "token-classification",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy="simple",
    )
