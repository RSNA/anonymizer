"""Blank or synthetic replacement of detected PHI spans."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import SlotScan, detect_phi
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import PhiEntity
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory

ReplaceMode = Literal["blank", "synth"]
REPLACE_MODE_VALUES: tuple[ReplaceMode, ...] = ("blank", "synth")


def replace_mode_display_label(mode: ReplaceMode) -> str:
    from anonymizer.utils.translate import _

    if mode == "synth":
        return _("Synthetic")
    return _("Blank")


def replace_mode_menu_labels() -> tuple[str, ...]:
    return tuple(replace_mode_display_label(member) for member in REPLACE_MODE_VALUES)


def normalize_replace_mode(value: object | None, *, default: ReplaceMode = "blank") -> ReplaceMode:
    text = str(value or "").strip().lower()
    if text in ("synth", "synthetic"):
        return "synth"
    if text in ("blank", "remove", "clear"):
        return "blank"
    from anonymizer.utils.translate import _

    if str(value or "") == _("Synthetic"):
        return "synth"
    if str(value or "") == _("Blank"):
        return "blank"
    return default


def apply_entities(
    text: str,
    entities: Sequence[PhiEntity],
    *,
    mode: Literal["blank", "synth"] = "blank",
    locale: str = "en_US",
    synth: SyntheticPhiFactory | None = None,
) -> str:
    """Replace the given ``entities`` in ``text`` (right-to-left). Callers may pass a user-filtered subset."""
    if not entities:
        return text
    factory = synth
    if mode == "synth" and factory is None:
        factory = SyntheticPhiFactory(locale=locale)
    ordinals: dict[str, int] = {}
    replacements: list[tuple[PhiEntity, str]] = []
    for ent in sorted(entities, key=lambda e: (e.start, e.end)):
        ord_i = ordinals.get(ent.label, 0)
        ordinals[ent.label] = ord_i + 1
        if mode == "blank":
            replacements.append((ent, ""))
        else:
            assert factory is not None
            replacements.append(
                (ent, factory.generate(ent.label, ordinal=ord_i, source_fragment=text[ent.start : ent.end]))
            )
    out = text
    for ent, repl in sorted(replacements, key=lambda x: x[0].start, reverse=True):
        out = out[: ent.start] + repl + out[ent.end :]
    if mode == "blank":
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r" ?\n ?", "\n", out).strip(" \t")
    return out


def replace_phi(
    text: str,
    *,
    mode: Literal["blank", "synth"] = "blank",
    locale: str = "en_US",
    synth: SyntheticPhiFactory | None = None,
    apply_guard: bool = True,
) -> tuple[str, list[PhiEntity]]:
    """
    Detect PHI and replace spans right-to-left.

    ``blank`` → empty string (VR-safe). ``synth`` → label-appropriate synthetic text.
    """
    entities = detect_phi(text, locale=locale, apply_guard=apply_guard)
    if not entities:
        return text, []
    return apply_entities(text, entities, mode=mode, locale=locale, synth=synth), entities


def apply_scans(
    scans: Sequence[SlotScan],
    *,
    mode: ReplaceMode = "blank",
    synth: SyntheticPhiFactory | None = None,
    locale: str = "en_US",
) -> int:
    """Replace entities in each slot via ``slot.write``. Returns the number of slots changed."""
    changed = 0
    for scan in scans:
        if not scan.entities:
            continue
        new_text = apply_entities(scan.slot.text, scan.entities, mode=mode, locale=locale, synth=synth)
        if new_text != scan.slot.text:
            scan.slot.write(new_text)
            scan.slot.text = new_text
            changed += 1
    return changed
