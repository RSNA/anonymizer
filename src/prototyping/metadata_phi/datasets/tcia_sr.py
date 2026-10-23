"""Load TCIA DICOM-SR-Breast-Clinical (wgllssg1) Structured Reports."""

from dataclasses import dataclass
from pathlib import Path

from prototyping.metadata_phi.extract import extract_from_file
from prototyping.metadata_phi.types import TextChunk

# CodeMeaning / boilerplate labels that are not narrative clinical prose.
_SKIP_TAGS_SUBSTR = (
    "ConceptNameCodeSequence",
    "Language of Content",
    "Country of Language",
    "Subject Sex",
    "Racial group",
    "Patient Characteristics",
    "Health status",
    "Supplementary Data",
)


@dataclass(frozen=True, slots=True)
class TciaSrDoc:
    path: Path
    chunks: list[TextChunk]

    @property
    def narrative_text(self) -> str:
        """Join free-text / description chunks useful for PHI NER eval."""
        parts: list[str] = []
        for c in self.chunks:
            if c.tag_or_path in {"PatientName", "PatientID"}:
                continue  # research IDs (TCGA-*), not person-name gold
            if any(s in c.tag_or_path for s in ("ConceptNameCodeSequence",)):
                # Keep CodeMeaning only when it is not pure schema boilerplate —
                # skip those via length/content filters below.
                if c.tag_or_path.endswith("CodeMeaning") and len(c.text) < 40:
                    if c.text in {
                        "Narrative Summary",
                        "Procedure reported",
                        "Patient Characteristics",
                        "Supplementary Data",
                        "Subject Sex",
                        "Racial group",
                        "Health status",
                        "Language of Content Item and Descendants",
                        "Country of Language",
                    }:
                        continue
            if c.tag_or_path.endswith("TextValue") or c.tag_or_path in {
                "StudyDescription",
                "SeriesDescription",
            }:
                parts.append(c.text)
        return "\n".join(parts)


def iter_sr_files(root: str | Path, *, limit: int | None = None) -> list[Path]:
    root = Path(root)
    paths = sorted(root.rglob("*.dcm"))
    if limit is not None:
        paths = paths[:limit]
    return paths


def load_sr(path: Path, *, locale: str = "en_US") -> TciaSrDoc:
    chunks = extract_from_file(path, locale=locale)
    return TciaSrDoc(path=path, chunks=chunks)


def iter_docs(root: str | Path, *, limit: int | None = None, locale: str = "en_US") -> list[TciaSrDoc]:
    return [load_sr(p, locale=locale) for p in iter_sr_files(root, limit=limit)]
