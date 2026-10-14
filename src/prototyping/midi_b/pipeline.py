"""MIDI-B de-id run — same steps 1–7 as PseudoPHI, no gold pairs."""

from __future__ import annotations

import json
import logging
import shutil
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pydicom

from anonymizer.controller.ai.embedded_phi.metadata.process_private_tags_tcia import (
    process_private_tags_tcia,
)
from prototyping.midi_b.inventory import MidiInstance
from prototyping.midi_b.mappings import write_patid_mapping, write_uid_mapping
from prototyping.pseudo_phi_deid.pipeline.clinical import ClinicalSession
from prototyping.pseudo_phi_deid.pipeline.metadata_ner import scrub_dataset
from prototyping.pseudo_phi_deid.pipeline.ner_residual_cleanup import (
    cleanup_dataset_residuals,
)
from prototyping.pseudo_phi_deid.pipeline.run import RunConfig

logger = logging.getLogger(__name__)


@dataclass
class MidiRunResult:
    candidate_dir: Path
    uid_mapping: Path
    patid_mapping: Path
    histogram: dict[str, int]
    ner_samples: list[dict]
    n_instances: int
    config: RunConfig


def run_instances(
    instances: Sequence[MidiInstance],
    out_dir: Path,
    config: RunConfig,
) -> MidiRunResult:
    """Run Clinical + private KB + NER + residual cleanup; emit mapping CSVs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = out_dir / "candidates"
    # Refresh candidates/mappings only — keep inventory.json and logs beside them.
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    maps_dir = out_dir / "mappings"
    if maps_dir.exists():
        shutil.rmtree(maps_dir)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir(parents=True, exist_ok=True)
    uid_path = maps_dir / "uid_mapping.csv"
    patid_path = maps_dir / "patid_mapping.csv"

    hist: Counter[str] = Counter()
    samples: list[dict] = []
    session: ClinicalSession | None = None
    try:
        if config.use_script:
            session = ClinicalSession(config.script_path)
            session.__enter__()

        total = len(instances)
        for i, inst in enumerate(instances, 1):
            if i == 1 or i % 50 == 0 or i == total:
                logger.info(
                    "midi_b %s %d/%d %s",
                    config.mode,
                    i,
                    total,
                    inst.sop_uid[:24],
                )
            ds = pydicom.dcmread(str(inst.path), force=True)
            phi_sop = inst.sop_uid or str(getattr(ds, "SOPInstanceUID", "") or "").strip()
            if not phi_sop:
                logger.warning("skip no SOPInstanceUID: %s", inst.path)
                continue

            # Step 1 — Clinical script (public tags; privates left for step 2).
            if config.use_script:
                assert session is not None
                ds = session.apply(ds)

            # Step 2 — TCIA Private Tag KB.
            if config.use_script or config.use_openmed:
                process_private_tags_tcia(ds)

            # Steps 3–5 — extract / prepare / bulk NER + taxonomy scrub.
            if config.use_openmed:
                resolve = (
                    session.anon.model.resolve_tag_keep
                    if session is not None and session.anon is not None
                    else None
                )
                anon_ptid = str(getattr(ds, "PatientID", "") or "ANON").strip() or "ANON"
                ds, h, samp = scrub_dataset(
                    ds,
                    field_wrap=config.field_wrap,
                    caret_space=config.caret_space,
                    anon_ptid=anon_ptid,
                    project_id="midi_b",
                    resolve_tag_keep=resolve,
                )
                hist.update(h)
                for s in samp:
                    if len(samples) < 50:
                        samples.append(s)
                # Step 6 — residual cleanup after NER blanks.
                cleanup_dataset_residuals(ds)

            # Step 7 — persist candidate (keyed by original patient/sop for traceability).
            dest = (
                candidate_dir
                / inst.patient_id
                / f"{phi_sop.replace('.', '_')}.dcm"
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            ds.save_as(str(dest), enforce_file_format=False)

        # Mappings must be dumped before ClinicalSession tears down the temp DB.
        if session is not None and session.anon is not None:
            write_uid_mapping(session.anon.model, uid_path)
            write_patid_mapping(session.anon.model, patid_path)
        else:
            # Script-off modes still need empty mapping files for the scorer shape.
            uid_path.write_text("id_old,id_new\n", encoding="utf-8")
            patid_path.write_text("id_old,id_new\n", encoding="utf-8")
    finally:
        if session is not None:
            session.__exit__(None, None, None)

    cfg = {
        "mode": config.mode,
        "use_script": config.use_script,
        "use_openmed": config.use_openmed,
        "field_wrap": config.field_wrap,
        "caret_space": config.caret_space,
        "n_instances": total,
        "candidate_dir": str(candidate_dir),
        "uid_mapping": str(uid_path),
        "patid_mapping": str(patid_path),
    }
    (out_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (out_dir / "ner_histogram.json").write_text(
        json.dumps(dict(hist), indent=2), encoding="utf-8"
    )

    return MidiRunResult(
        candidate_dir=candidate_dir,
        uid_mapping=uid_path,
        patid_mapping=patid_path,
        histogram=dict(hist),
        ner_samples=samples,
        n_instances=total,
        config=config,
    )
