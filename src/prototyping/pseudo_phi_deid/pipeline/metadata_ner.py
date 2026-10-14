"""OpenMed scrub on free-text DICOM VRs (bulk NER; PseudoPHI steps 3–5).

3. Collect non-empty TEXT_VRs
4. Prepare: NER only for ``tag_keep`` keep / ``@process`` / ``@always``;
   private creator IDs (``gggg,0010–00FF``) kept on dataset but never NER'd;
   caret→space; wrap (private data → TCIA KB name when known);
   ``@safe()`` excluded from NER
5. Bulk OpenMed detect + taxonomy scrub on NER spans

Step 6 (``ner_residual_cleanup``) runs after this module.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable

from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    TEXT_VRS,
    element_display_name,
)
from anonymizer.controller.ai.embedded_phi.metadata.process_private_tags_tcia import (
    _is_private_creator,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import (
    Entity,
    detect_entities,
    detect_entities_in_segments,
    _DEFAULT_SEGMENT_MAX_CHARS,
)
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    wrap_field_for_ner,
)
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import generate_synthetic_phi

from prototyping.pseudo_phi_deid.taxonomy import normalize_raw, resolve_action

logger = logging.getLogger(__name__)

ResolveTagKeep = Callable[[str], str | None]


def _caret_space(text: str) -> str:
    return " ".join(p for p in str(text or "").replace("^", " ").split() if p)


def _tag_hex(elem: DataElement) -> str:
    return f"{int(elem.tag):08X}"


def exclude_from_ner(
    path: str,
    elem: DataElement,
    *,
    resolve_tag_keep: ResolveTagKeep | None = None,
) -> bool:
    """Drop private creators and ``@safe()``; NER only keep / ``@process`` / ``@always``."""
    if _is_private_creator(elem.tag):
        return True
    if resolve_tag_keep is None:
        return False
    op = resolve_tag_keep(_tag_hex(elem)) or ""
    if op.startswith("@safe"):
        return True
    return not (op == "" or op.startswith(("@keep", "@process", "@always")))


def ner_field_label(ds: Dataset, path: str, elem: DataElement) -> str:
    if elem.tag.is_private:
        return element_display_name(ds, elem)
    return path.split(".")[-1] or (elem.keyword or _tag_hex(elem))


def collect_text_fields(ds: Dataset) -> list[tuple[str, str, DataElement]]:
    out: list[tuple[str, str, DataElement]] = []

    def walk(current: Dataset, prefix: str = "") -> None:
        for elem in current:
            if elem.VR == "SQ" and elem.value:
                for i, item in enumerate(elem.value):
                    if isinstance(item, Dataset):
                        name = elem.keyword or str(elem.tag)
                        walk(item, f"{prefix}{name}[{i}].")
                continue
            if elem.VR not in TEXT_VRS:
                continue
            kw = elem.keyword or str(elem.tag)
            try:
                val = str(elem.value) if elem.value is not None else ""
            except Exception:
                continue
            if not val.strip():
                continue
            out.append((f"{prefix}{kw}", val, elem))

    walk(ds)
    return out


def prepare_ner_fields(
    ds: Dataset,
    *,
    field_wrap: bool = True,
    caret_space: bool = True,
    resolve_tag_keep: ResolveTagKeep | None = None,
) -> tuple[list[str], list[tuple[str, str, DataElement, int]], dict[str, int]]:
    fields = collect_text_fields(ds)
    segments: list[str] = []
    meta: list[tuple[str, str, DataElement, int]] = []
    dropped = 0
    for path, val, elem in fields:
        if exclude_from_ner(path, elem, resolve_tag_keep=resolve_tag_keep):
            dropped += 1
            continue
        plain = _caret_space(val) if caret_space else val.strip()
        if field_wrap:
            wrap_name = elem.keyword or ner_field_label(ds, path, elem)
            ner_text, vstart, _vend = wrap_field_for_ner(wrap_name, plain)
            segments.append(ner_text)
            meta.append((path, plain, elem, vstart))
        else:
            segments.append(plain)
            meta.append((path, plain, elem, 0))
    return segments, meta, {"extracted": len(fields), "kept": len(meta), "dropped": dropped}


def scrub_dataset(
    ds: Dataset,
    *,
    locale: str = "en_US",
    field_wrap: bool = True,
    caret_space: bool = True,
    project_id: str = "pseudo_phi_deid",
    anon_ptid: str = "ANON",
    detect_only: bool = False,
    max_chars: int = _DEFAULT_SEGMENT_MAX_CHARS,
    resolve_tag_keep: ResolveTagKeep | None = None,
) -> tuple[Dataset, dict[str, int], list[dict]]:
    segments, meta, prep = prepare_ner_fields(
        ds,
        field_wrap=field_wrap,
        caret_space=caret_space,
        resolve_tag_keep=resolve_tag_keep,
    )
    logger.info(
        "step4.prepare: extracted=%d kept=%d dropped=%d",
        prep["extracted"],
        prep["kept"],
        prep["dropped"],
    )
    if not segments:
        return ds, {}, []

    per_seg = detect_entities_in_segments(
        segments,
        locale=locale,
        max_chars=max_chars,
        scan_fn=lambda joined: detect_entities(joined, locale=locale),
    )
    n_ents = sum(len(e) for e in per_seg)

    hist: Counter[str] = Counter()
    samples: list[dict] = []
    n_scrubbed = 0
    for (path, plain, elem, vstart), ents in zip(meta, per_seg, strict=True):
        remapped: list[Entity] = []
        for ent in ents:
            start = ent.start - vstart
            end = ent.end - vstart
            if start < 0 or end > len(plain) or start >= end:
                continue
            remapped.append(
                Entity(
                    label=ent.label,
                    start=start,
                    end=end,
                    score=ent.score,
                    raw_label=ent.raw_label,
                )
            )
        for ent in remapped:
            hist[normalize_raw(ent.raw_label or ent.label)] += 1
        if remapped and len(samples) < 40:
            samples.append(
                {"tag_path": path, "plain": plain, "tagged": _format_tagged(plain, remapped)}
            )
        if detect_only or not remapped:
            continue
        new_plain = _apply(
            plain, remapped, project_id=project_id, anon_ptid=anon_ptid, locale=locale
        )
        if new_plain != plain:
            try:
                elem.value = new_plain
                n_scrubbed += 1
            except Exception as exc:
                logger.warning("write failed %s: %s", path, exc)
    logger.debug("step5.scrub: fields=%d spans=%d", n_scrubbed, n_ents)
    return ds, dict(hist), samples


def _format_tagged(plain: str, entities: list[Entity]) -> str:
    parts: list[str] = []
    last = 0
    for ent in sorted(entities, key=lambda e: (e.start, e.end)):
        parts.append(plain[last : ent.start])
        raw = normalize_raw(ent.raw_label or ent.label)
        parts.append(f"<{raw}>{plain[ent.start : ent.end]}</{raw}>")
        last = ent.end
    parts.append(plain[last:])
    return "".join(parts)


def _apply(
    text: str,
    entities: list[Entity],
    *,
    project_id: str,
    anon_ptid: str,
    locale: str,
) -> str:
    body = text
    ordinals: dict[str, int] = {}
    planned: list[tuple[int, int, str]] = []
    for ent in sorted(entities, key=lambda e: (e.start, e.end)):
        action = resolve_action(ent.raw_label or ent.label)
        if action in {"ignore", "defer-to-script"}:
            continue
        frag = body[ent.start : ent.end]
        raw = normalize_raw(ent.raw_label or "")
        if action == "blank":
            planned.append((ent.start, ent.end, ""))
            continue
        synth_label = ent.label if ent.label in {
            "NAME", "LOCATION", "ID", "PHONE", "EMAIL", "DATE"
        } else "NAME"
        if raw in {"CITY", "STATE", "ZIP", "ZIPCODE", "STREET", "STREET_ADDRESS", "ADDRESS"}:
            synth_label = "LOCATION"
        elif raw in {"PHONE", "PHONE_NUMBER"}:
            synth_label = "PHONE"
        elif raw in {"EMAIL", "EMAIL_ADDRESS"}:
            synth_label = "EMAIL"
        elif raw in {"CUSTOMER_ID"}:
            synth_label = "ID"
        key = f"{raw}:{synth_label}"
        ord_i = ordinals.get(key, 0)
        ordinals[key] = ord_i + 1
        tokens = frag.replace("^", " ").replace(",", " ").split()
        replacement = generate_synthetic_phi(
            synth_label,
            project_id=project_id,
            anon_ptid=anon_ptid,
            locale=locale,
            ordinal=ord_i,
            source_fragment=frag,
        )
        if len(tokens) == 1 and raw in {"FIRST_NAME", "FIRSTNAME"}:
            replacement = replacement.split()[0] if replacement.split() else replacement
        elif len(tokens) == 1 and raw in {"LAST_NAME", "LASTNAME"}:
            parts = replacement.replace("^", " ").split()
            replacement = parts[-1] if parts else replacement
        planned.append((ent.start, ent.end, replacement))
    out = body
    for start, end, repl in sorted(planned, key=lambda t: t[0], reverse=True):
        out = out[:start] + repl + out[end:]
    return " ".join(out.split())
