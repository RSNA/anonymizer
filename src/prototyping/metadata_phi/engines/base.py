"""PhiEngine protocol and registry."""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from prototyping.metadata_phi.types import Span


@runtime_checkable
class PhiEngine(Protocol):
    name: str

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        ...

    def is_available(self) -> bool:
        ...


def _registry() -> dict[str, Callable[[], PhiEngine]]:
    from prototyping.metadata_phi.engines.longformer_deid import LongformerDeidEngine
    from prototyping.metadata_phi.engines.obi_deid import ObiDeidEngine
    from prototyping.metadata_phi.engines.presidio_transformers import PresidioTransformersEngine
    from prototyping.metadata_phi.engines.regex_spacy import RegexSpacyEngine
    from prototyping.metadata_phi.engines.spacy_ner import SpacyNerEngine

    return {
        # Fair comparison names
        "patterns": lambda: RegexSpacyEngine(use_spacy=False),
        "spacy_ner": SpacyNerEngine,
        # Legacy / mixed names (presidio still merges locale patterns today)
        "regex_spacy": lambda: RegexSpacyEngine(use_spacy=False),
        "presidio_transformers": PresidioTransformersEngine,
        # Neural: locale HF_DEID_MODEL (OpenMed ClinicalE5-Small by default)
        "openmed_pii": lambda: ObiDeidEngine(merge_patterns=False),
        "obi_deid": lambda: ObiDeidEngine(merge_patterns=False),
        "longformer_deid": LongformerDeidEngine,
    }


def available_engines() -> list[str]:
    return list(_registry().keys())


def get_engine(name: str) -> PhiEngine:
    factory = _registry().get(name)
    if factory is None:
        raise KeyError(f"Unknown engine {name!r}. Choose from: {', '.join(available_engines())}")
    eng = factory()
    # Keep reported name aligned with the registry key used for scoring.
    if getattr(eng, "name", None) != name:
        try:
            eng.name = name  # type: ignore[misc]
        except Exception:
            pass
    return eng
