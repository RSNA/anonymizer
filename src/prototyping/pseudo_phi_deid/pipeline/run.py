"""PseudoPHI header pipeline — steps 1–7 (score is step 8, outside this module).

1. anonymizer script (Retain Safe Private via AnonymizerController walk)
2. Extract remaining non-empty TEXT_VRS
3. Prepare NER: drop stamps + script-generated fields; caret→space; wrap
   (private tags → TCIA KB description when available)
4. Bulk OpenMed detect + taxonomy scrub on NER spans
5. ner_residual_cleanup (dangling for/file, FORFILE, month+year tokens)
6. Persist candidates
7. Score vs DeIdentified gold (score_pairs / CLI)

No keyword wipe, no overlay strip, no pixel OCR, no radiology deny-lists.
"""

import logging
import shutil
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import pydicom

from prototyping.pseudo_phi_deid.pairs import InstancePair
from prototyping.pseudo_phi_deid.pipeline.script_session import AnonymizerSession, operation_resolver
from prototyping.pseudo_phi_deid.pipeline.metadata_ner import scrub_dataset
from prototyping.pseudo_phi_deid.pipeline.ner_residual_cleanup import (
    cleanup_dataset_residuals,
)

logger = logging.getLogger(__name__)


@dataclass
class RunConfig:
    """``combined`` is the only plan mode (steps 1–7 + score). Other modes are legacy CLI."""

    mode: str  # combined | script | openmed | ner_only
    use_script: bool = False
    use_openmed: bool = False
    field_wrap: bool = True  # step 4: prefix ``Keyword: ``
    caret_space: bool = True  # step 4: PN ``^`` → spaces
    script_path: Path | None = None
    subject_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_mode(cls, mode: str, **kwargs: object) -> Self:
        cfg = cls(mode=mode, **kwargs)  # type: ignore[arg-type]
        if mode == "script":
            cfg.use_script = True
            cfg.use_openmed = False
        elif mode == "openmed":
            cfg.use_script = False
            cfg.use_openmed = True
        elif mode == "combined":
            cfg.use_script = True
            cfg.use_openmed = True
        elif mode == "ner_only":
            # Script off — not plan-complete; identity left to caller / prior files.
            cfg.use_script = False
            cfg.use_openmed = True
        else:
            raise ValueError(
                f"unknown mode {mode!r}; plan path is 'combined' (steps 1–7 + score)"
            )
        return cfg


@dataclass
class RunResult:
    candidate_dir: Path
    histogram: dict[str, int]
    ner_samples: list[dict]
    pixel_modified: int  # always 0 — pixels out of this phase
    config: RunConfig


def run_pairs(
    pairs: Sequence[InstancePair],
    out_dir: Path,
    config: RunConfig,
) -> RunResult:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    hist: Counter[str] = Counter()
    samples: list[dict] = []
    session: AnonymizerSession | None = None
    try:
        if config.use_script:
            session = AnonymizerSession(config.script_path)
            session.__enter__()

        total = len(pairs)
        for i, pair in enumerate(pairs, 1):
            if i == 1 or i % 50 == 0 or i == total:
                logger.info("run %s %d/%d %s", config.mode, i, total, pair.eval_sop_uid[:24])
            ds = pydicom.dcmread(str(pair.eval_path), force=True)

            # Step 1 — anonymizer script (public + SAFE_PRIVATE KB walk).
            if config.use_script:
                assert session is not None
                ds = session.apply(ds)

            # Steps 2–4 — extract / prepare / bulk NER + taxonomy scrub.
            if config.use_openmed:
                resolve = (
                    operation_resolver(session.anon)
                    if session is not None and session.anon is not None
                    else None
                )
                ds, h, samp = scrub_dataset(
                    ds,
                    field_wrap=config.field_wrap,
                    caret_space=config.caret_space,
                    anon_ptid=pair.gold_patient_id,
                    operation_for_tag=resolve,
                )
                hist.update(h)
                for s in samp:
                    if len(samples) < 50:
                        samples.append(s)
                # Step 6 — residual cleanup after NER blanks.
                cleanup_dataset_residuals(ds)

            # Step 7 — persist candidate.
            dest = (
                out_dir
                / pair.eval_patient_id
                / f"{pair.eval_sop_uid.replace('.', '_')}.dcm"
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            ds.save_as(str(dest), enforce_file_format=False)
    finally:
        if session is not None:
            session.__exit__(None, None, None)

    return RunResult(
        candidate_dir=out_dir,
        histogram=dict(hist),
        ner_samples=samples,
        pixel_modified=0,
        config=config,
    )
