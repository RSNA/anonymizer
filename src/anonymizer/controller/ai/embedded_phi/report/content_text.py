"""Editable text regions yielded by report loaders."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class TextSlot:
    """One editable text value inside a DICOM object. ``write`` stores new text back on the dataset."""

    key: str
    context: str
    text: str
    write: Callable[[str], None] = field(repr=False, compare=False)
