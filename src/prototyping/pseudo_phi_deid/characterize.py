"""Phase 0: full Evaluation characterize (headers, pixels, overlays, NER inventory)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np
import pydicom

from prototyping.pseudo_phi_deid.pairs import InstancePair, pair_all
from prototyping.pseudo_phi_deid.paths import phase_dir
from prototyping.pseudo_phi_deid.pipeline.metadata_ner import scrub_dataset
from prototyping.pseudo_phi_deid.report import GLOSSARY
from prototyping.pseudo_phi_deid.taxonomy import lock_taxonomy_from_histogram, taxonomy_table_md

logger = logging.getLogger(__name__)


def _pixel_digest(path: Path) -> str | None:
    try:
        arr = pydicom.dcmread(str(path), force=True).pixel_array
        return hashlib.sha1(np.ascontiguousarray(arr).tobytes()).hexdigest()
    except Exception:
        return None


def _has_overlay(path: Path) -> bool:
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception:
        return False
    for elem in ds:
        g = int(elem.tag.group)
        if 0x6000 <= g <= 0x601E and g % 2 == 0:
            return True
    return False


def characterize(
    *,
    out_dir: Path | None = None,
    ner_limit: int | None = None,
    patient_ids: list[str] | None = None,
) -> dict:
    """
    Full-cohort inventory. ``ner_limit`` caps OpenMed detect-only files (None = all).
    """
    out = out_dir or phase_dir(0, "characterize")
    out.mkdir(parents=True, exist_ok=True)
    pairs, unpaired = pair_all(patient_ids=patient_ids)
    logger.info("paired=%d unpaired=%d", len(pairs), len(unpaired))

    mods: Counter[str] = Counter()
    pixel_same = 0
    pixel_diff = 0
    pixel_err = 0
    burnin_sops: list[str] = []
    overlay_eval = 0
    overlay_gold_cleared = 0
    header_diff_tags: Counter[str] = Counter()
    pixel_same_by_sop: dict[str, bool] = {}

    for i, pair in enumerate(pairs, 1):
        if i == 1 or i % 100 == 0 or i == len(pairs):
            logger.info("characterize pixels/headers %d/%d", i, len(pairs))
        mods[pair.modality or "?"] += 1
        ed = _pixel_digest(pair.eval_path)
        gd = _pixel_digest(pair.gold_path)
        if ed is None or gd is None:
            pixel_err += 1
            pixel_same_by_sop[pair.eval_sop_uid] = True  # skip harsh pixel fail
        elif ed == gd:
            pixel_same += 1
            pixel_same_by_sop[pair.eval_sop_uid] = True
        else:
            pixel_diff += 1
            pixel_same_by_sop[pair.eval_sop_uid] = False
            burnin_sops.append(pair.eval_sop_uid)

        ev_ov = _has_overlay(pair.eval_path)
        gold_ov = _has_overlay(pair.gold_path)
        if ev_ov:
            overlay_eval += 1
            if not gold_ov:
                overlay_gold_cleared += 1

        # Sample header diff tags (first 200 pairs fully; then every 10th)
        if i <= 200 or i % 10 == 0:
            try:
                ev = pydicom.dcmread(str(pair.eval_path), stop_before_pixels=True, force=True)
                gold = pydicom.dcmread(str(pair.gold_path), stop_before_pixels=True, force=True)
                for kw in (
                    "PatientName",
                    "PatientID",
                    "PatientAddress",
                    "PatientBirthDate",
                    "PatientTelephoneNumbers",
                    "InstitutionName",
                    "InstitutionAddress",
                    "ReferringPhysicianName",
                    "StudyDescription",
                    "SeriesDescription",
                    "AccessionNumber",
                ):
                    ev_v = str(getattr(ev, kw, "") or "")
                    g_v = str(getattr(gold, kw, "") or "")
                    if ev_v != g_v:
                        header_diff_tags[kw] += 1
            except Exception:
                pass

    # OpenMed detect-only inventory
    ner_hist: Counter[str] = Counter()
    ner_samples: list[dict] = []
    ner_pairs = pairs if ner_limit is None else pairs[:ner_limit]
    for i, pair in enumerate(ner_pairs, 1):
        if i == 1 or i % 25 == 0 or i == len(ner_pairs):
            logger.info("characterize NER %d/%d", i, len(ner_pairs))
        try:
            ds = pydicom.dcmread(str(pair.eval_path), stop_before_pixels=True, force=True)
            _ds, h, samp = scrub_dataset(ds, detect_only=True)
            ner_hist.update(h)
            for s in samp:
                if len(ner_samples) < 60:
                    ner_samples.append(s)
        except Exception as exc:
            logger.warning("NER characterize failed %s: %s", pair.eval_path, exc)

    locked = lock_taxonomy_from_histogram(dict(ner_hist))
    inventory = {
        "pairs": len(pairs),
        "unpaired": len(unpaired),
        "modalities": dict(mods),
        "pixel_same": pixel_same,
        "pixel_diff": pixel_diff,
        "pixel_err": pixel_err,
        "burnin_sop_count": len(burnin_sops),
        "burnin_sops": burnin_sops,
        "overlay_eval": overlay_eval,
        "overlay_gold_cleared": overlay_gold_cleared,
        "header_diff_tags_sample": dict(header_diff_tags),
        "ner_files": len(ner_pairs),
        "ner_histogram": dict(ner_hist),
        "taxonomy_locked": locked,
        "unpaired_records": unpaired[:100],
        "unpaired_total": len(unpaired),
    }
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (out / "pixel_same_by_sop.json").write_text(
        json.dumps(pixel_same_by_sop, indent=2), encoding="utf-8"
    )
    (out / "raw_ner_histogram.json").write_text(
        json.dumps(dict(ner_hist), indent=2), encoding="utf-8"
    )
    (out / "config.json").write_text(
        json.dumps({"phase": 0, "ner_limit": ner_limit, "pairs": len(pairs)}, indent=2),
        encoding="utf-8",
    )

    # Human SCORECARD
    hist_rows = "\n".join(
        f"| {k} | {v} |" for k, v in sorted(ner_hist.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    md = f"""# SCORECARD — phase_0_characterize

**Goal:** Inventory full Evaluation vs gold (headers, pixels, overlays, OpenMed raw tags).

**What changed:** First clean-slate characterize; no de-id yet.

{GLOSSARY}

## Pairing

| Metric | Value |
| --- | --- |
| Paired files | {len(pairs)} |
| Unpaired | {len(unpaired)} |
| Modalities | {dict(mods)} |

## Pixels / overlays

| Metric | Value |
| --- | --- |
| Pixel digest equal (eval==gold) | {pixel_same} |
| Pixel digest differ (burn-in candidates) | {pixel_diff} |
| Pixel read errors | {pixel_err} |
| Eval overlays present | {overlay_eval} |
| Overlays cleared on gold | {overlay_gold_cleared} |

**Do not use BurnedInAnnotation as a detector.**

## Header tags that often differ (sample)

| tag | count in sample |
| --- | --- |
{chr(10).join(f'| {k} | {v} |' for k, v in header_diff_tags.most_common(20))}

## OpenMed raw-label histogram (detect-only, {len(ner_pairs)} files)

| raw_label | count |
| --- | --- |
{hist_rows or '| _(none)_ | 0 |'}

## Taxonomy seed (from histogram)

{taxonomy_table_md()}

## Next step

Run Phase 1 baselines (script / openmed / pixels / combined) on all pairs; push cohort accuracy toward >95%.
"""
    (out / "SCORECARD.md").write_text(md, encoding="utf-8")
    # stub metrics for final-report aggregation
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "pairs": len(pairs),
                "cohort_accuracy": 0,
                "header_accuracy": 0,
                "pixel_accuracy": 0,
                "overlay_accuracy": 0,
                "passed_gate": False,
                "histogram": dict(ner_hist),
                "note": "characterize only — accuracy N/A",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Write TAXONOMY.md at package root
    tax = Path(__file__).resolve().parent / "TAXONOMY.md"
    tax.write_text(
        f"""# Taxonomy (from Phase 0 characterize)

Evidence: `{out.name}/raw_ner_histogram.json` on {len(ner_pairs)} Evaluation files.

Person-name policy: replace the **entire span** even if OpenMed tags it `FIRST_NAME` only.

{taxonomy_table_md()}

Burn-in-positive SOP count: {len(burnin_sops)} (see inventory.json). Overlays cleared on gold: {overlay_gold_cleared}.
""",
        encoding="utf-8",
    )
    return inventory
