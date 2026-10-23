"""Locale → asset / model resolution for metadata PHI detection."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
_LOCALES_ROOT = _PACKAGE_ROOT / "locales"

# Relative to repo src/ so product OCR whitelists stay the single source of truth.
_WHITELIST_ROOT = _PACKAGE_ROOT.parent.parent / "anonymizer" / "assets" / "locales"


@dataclass(frozen=True, slots=True)
class LocalePack:
    locale: str
    cue_words: dict[str, list[str]]
    radiology_deny: frozenset[str]
    id_patterns_module: Any
    date_patterns_module: Any
    spacy_model: str
    hf_deid_model: str
    hf_longformer_model: str
    whitelist_dir: Path
    models: dict[str, str] = field(default_factory=dict)


def list_locales() -> list[str]:
    if not _LOCALES_ROOT.is_dir():
        return []
    return sorted(p.name for p in _LOCALES_ROOT.iterdir() if p.is_dir() and (p / "cue_words.json").is_file())


def _load_radiology_deny(path: Path) -> frozenset[str]:
    terms: set[str] = set()
    if not path.is_file():
        return frozenset()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            terms.add(line.casefold())
    return frozenset(terms)


def load_ocr_whitelist_terms(locale: str) -> frozenset[str]:
    """Load modality OCR whitelist terms for *locale* (shared with product assets)."""
    root = _WHITELIST_ROOT / locale / "whitelists"
    terms: set[str] = set()
    if not root.is_dir():
        return frozenset()
    for path in root.glob("*.txt"):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                terms.add(line.casefold())
    return frozenset(terms)


@lru_cache(maxsize=8)
def get_locale_pack(locale: str = "en_US") -> LocalePack:
    locale_dir = _LOCALES_ROOT / locale
    if not locale_dir.is_dir():
        available = ", ".join(list_locales()) or "(none)"
        raise KeyError(f"Locale pack {locale!r} not found. Available: {available}")

    cue_path = locale_dir / "cue_words.json"
    deny_path = locale_dir / "radiology_deny.txt"
    cue_words = json.loads(cue_path.read_text(encoding="utf-8"))

    # Import locale-specific pattern modules by path-derived module name.
    id_mod = import_module(f"prototyping.metadata_phi.locales.{locale}.id_patterns")
    date_mod = import_module(f"prototyping.metadata_phi.locales.{locale}.date_patterns")

    models = {
        "spacy": getattr(id_mod, "SPACY_MODEL", "en_core_web_sm"),
        "hf_deid": getattr(id_mod, "HF_DEID_MODEL", "obi/deid_roberta_i2b2"),
        "hf_longformer": getattr(id_mod, "HF_LONGFORMER_MODEL", "obi/deid_roberta_i2b2"),
    }

    return LocalePack(
        locale=locale,
        cue_words=cue_words,
        radiology_deny=_load_radiology_deny(deny_path),
        id_patterns_module=id_mod,
        date_patterns_module=date_mod,
        spacy_model=models["spacy"],
        hf_deid_model=models["hf_deid"],
        hf_longformer_model=models["hf_longformer"],
        whitelist_dir=_WHITELIST_ROOT / locale / "whitelists",
        models=models,
    )
