"""MIDI-B 2024 VAL held-out evaluation (final check; not for method selection)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from prototyping.metadata_phi.dataset_schema import SCORED_LABELS
from prototyping.metadata_phi.engines.base import get_engine
from prototyping.metadata_phi.eval_dataset import BinaryCM, _format_cm
from prototyping.metadata_phi.extract import extract_from_file, is_uid_metadata_tag
from prototyping.metadata_phi.pipeline import analyze_text


def _iter_study_texts(data_dir: Path) -> list[dict]:
    """One concatenated free-text blob per study (non-UID tags)."""
    by_study: dict[str, list[str]] = {}
    paths: dict[str, str] = {}
    for path in sorted(data_dir.rglob("*.dcm")):
        chunks = extract_from_file(path)
        if not chunks:
            continue
        study = chunks[0].sop_uid  # fallback
        try:
            from pydicom import dcmread

            ds = dcmread(str(path), stop_before_pixels=True, force=True)
            study = str(getattr(ds, "StudyInstanceUID", "") or study)
        except Exception:  # noqa: BLE001
            pass
        parts = [
            c.text
            for c in chunks
            if c.text.strip() and not is_uid_metadata_tag(c.tag_or_path)
        ]
        if not parts:
            continue
        by_study.setdefault(study, [])
        # Keep first file's text only per study
        if study not in paths:
            by_study[study] = parts
            paths[study] = str(path)
    rows = []
    for i, (study, parts) in enumerate(by_study.items()):
        rows.append(
            {
                "id": f"midi_b_{i:03d}",
                "study": study,
                "path": paths[study],
                "text": "\n".join(parts),
            }
        )
    return rows


def run_midi_b_heldout(
    midi_dir: Path,
    *,
    engines: list[str],
    locale: str = "en_US",
    apply_guard: bool = True,
) -> str:
    data = midi_dir / "data" if (midi_dir / "data").is_dir() else midi_dir
    rows = _iter_study_texts(data)
    readme = {
        "role": "heldout_final_test",
        "source_dir": str(midi_dir),
        "n_studies": len(rows),
        "note": (
            "Local MIDI-B-2024-VAL tree is the de-identified validation side. "
            "Expected PHI is treated as negative (no residual patient PHI gold). "
            "Document false-alarm rate is the primary signal here."
        ),
    }
    sections = [
        "# MIDI-B 2024 VAL held-out evaluation",
        "",
        json.dumps(readme, indent=2),
        "",
        f"N_studies={len(rows)} locale={locale} guard={'on' if apply_guard else 'off'}",
        "",
        "Expected: no PHI (de-identified IDs). "
        "Predicted positive = any scored-label span.",
        "",
    ]
    for engine_name in engines:
        t0 = time.perf_counter()
        eng = get_engine(engine_name)
        sections.append(f"# Engine: `{engine_name}`")
        sections.append("")
        if not eng.is_available():
            sections.append(f"SKIP: {getattr(eng, '_error', 'unavailable')}")
            sections.append("")
            continue
        cm = BinaryCM()
        label_hits: dict[str, int] = {lab: 0 for lab in SCORED_LABELS}
        dirty_docs = 0
        for row in rows:
            pred = [
                s
                for s in analyze_text(
                    row["text"],
                    engine=eng,
                    locale=locale,
                    apply_guard=apply_guard,
                )
                if s.label in SCORED_LABELS
            ]
            # Expected always negative on this local VAL tree
            cm.add(False, bool(pred))
            if pred:
                dirty_docs += 1
                for s in pred:
                    label_hits[s.label] = label_hits.get(s.label, 0) + 1
        sections.append(_format_cm("Document PHI present? (expected = no)", cm))
        sections.append(
            f"docs_with_prediction={dirty_docs}/{len(rows)} "
            f"label_span_counts={{{', '.join(f'{k}: {v}' for k, v in label_hits.items() if v)}}}"
        )
        sections.append("")
        sections.append(f"_elapsed_seconds={time.perf_counter() - t0:.1f}_")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"
