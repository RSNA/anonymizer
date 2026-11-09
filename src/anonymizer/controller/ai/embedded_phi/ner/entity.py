"""PHI span shared by NER and date/time pattern helpers.

Public API
----------
Entity
    One PHI span: product label plus character offsets into the source string.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Entity:
    """One PHI span: product label plus character offsets into the source string.

    score is the model's softmax confidence for raw_label (fine-grained HF
    class), not for the mapped product label. The NER engine keeps every mapped
    span; pixel Embedded PHI and Clean Descriptors decide apply PhiMatchMode
    floors and the whitelist-vs-NER contest. UI hover shows label only.

    replacement: when set (metadata PHI tagged with a DICOM keyword as
    label), replace_entities always writes this string — the anonymized
    DICOM value — instead of blanking or generate_synthetic_phi.
    """

    label: str
    start: int
    end: int
    score: float = 1.0
    raw_label: str = ""
    replacement: str | None = None

    def text_of(self, source: str) -> str:
        """
        Return the substring of source covered by this entity.

        Args:
            source: Full source string into which start/end index.

        Returns:
            Slice source[start:end].
        """
        return source[self.start : self.end]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize this entity to a plain dict.

        Returns:
            Mapping of field names to values (via dataclasses.asdict).
        """
        return asdict(self)
