"""Resolve locale packs for phi_ner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType

from anonymizer.controller.ai.embedded_phi.ner.phi_entity import SUPPORTED_DETECT_LOCALES

_LOCALES_ROOT = Path(__file__).resolve().parent / "locales"
_WHITELIST_ROOT = Path(__file__).resolve().parents[4] / "assets" / "locales"


@dataclass(frozen=True)
class LocalePack:
    locale: str
    cue_words: dict[str, list[str]]
    id_patterns_module: ModuleType
    date_patterns_module: ModuleType
    spacy_model: str
    hf_deid_model: str


def list_locales() -> list[str]:
    if not _LOCALES_ROOT.is_dir():
        return []
    return sorted(
        p.name for p in _LOCALES_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")
    )


def detect_locale_supported(locale: str) -> bool:
    return locale in SUPPORTED_DETECT_LOCALES and locale in list_locales()


def load_ocr_whitelist_terms(locale: str) -> frozenset[str]:
    """Load modality OCR whitelist terms for *locale* (shared with product assets)."""
    root = _WHITELIST_ROOT / locale / "whitelists"
    if not root.is_dir():
        root = _WHITELIST_ROOT / "en_US" / "whitelists"
    terms: set[str] = set()
    if not root.is_dir():
        return frozenset()
    for path in root.glob("*.txt"):
        for line in path.read_text(encoding="utf-8").splitlines():
            t = line.strip().casefold()
            if t and not t.startswith("#"):
                terms.add(t)
    return frozenset(terms)


def get_locale_pack(locale: str = "en_US") -> LocalePack:
    locale_dir = _LOCALES_ROOT / locale
    if not locale_dir.is_dir():
        available = ", ".join(list_locales()) or "(none)"
        raise KeyError(f"Locale pack {locale!r} not found. Available: {available}")

    cue_path = locale_dir / "cue_words.json"
    cues: dict[str, list[str]] = {}
    if cue_path.is_file():
        cues = json.loads(cue_path.read_text(encoding="utf-8"))

    id_mod = import_module(f"anonymizer.controller.ai.embedded_phi.ner.locales.{locale}.id_patterns")
    date_mod = import_module(f"anonymizer.controller.ai.embedded_phi.ner.locales.{locale}.date_patterns")

    return LocalePack(
        locale=locale,
        cue_words=cues,
        id_patterns_module=id_mod,
        date_patterns_module=date_mod,
        spacy_model=getattr(id_mod, "SPACY_MODEL", "en_core_web_sm"),
        hf_deid_model=getattr(
            id_mod, "HF_DEID_MODEL", "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1"
        ),
    )
