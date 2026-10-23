"""Build a fair English eval corpus for metadata / report PHI detection.

Outputs under fixtures/en_US/corpus/ (local data paths; not committed bulky dumps
unless small). See metadata_phi_EXPERIMENT.md § Evaluation plan.
"""

import argparse
import csv
import json
import random
import re
from pathlib import Path

from prototyping.metadata_phi.datasets import (
    DEFAULT_HEROLIM_SR_DIR,
    DEFAULT_MIDI_B_VAL_DIR,
    DEFAULT_OPENI_DIR,
    DEFAULT_PSEUDO_PHI_DEID_DIR,
    DEFAULT_PSEUDO_PHI_EVAL_DIR,
    DEFAULT_REXERR_DIR,
    DEFAULT_TCIA_SR_DIR,
)
from prototyping.metadata_phi.datasets.openi import iter_reports

_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "en_US" / "corpus"
_HELDOUT = Path(__file__).resolve().parents[1] / "fixtures" / "en_US" / "heldout"

_DATE_ISO = re.compile(
    r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
)

# Fake identities only — never real patients.
_IDENTITIES: list[dict[str, str]] = [
    {
        "name": "Helen Park",
        "dob_slash": "03/14/1962",
        "dob_iso": "1962-03-14",
        "addr": "12 Oak Street, Boston, MA 02108",
        "city": "Boston",
        "phone": "(555) 123-4567",
        "email": "helen.park@example.org",
        "mrn": "4455667",
        "ssn": "123-45-6789",
    },
    {
        "name": "Robert Chen",
        "dob_slash": "11/03/1958",
        "dob_iso": "1958-11-03",
        "addr": "2200 Market Street, Philadelphia, PA 19103",
        "city": "Philadelphia",
        "phone": "(215) 555-0198",
        "email": "r.chen@example.com",
        "mrn": "9988776",
        "ssn": "987-65-4321",
    },
    {
        "name": "Maria Santos",
        "dob_slash": "07/22/1975",
        "dob_iso": "1975-07-22",
        "addr": "4821 Willow Creek Drive, Austin, TX 78745",
        "city": "Austin",
        "phone": "512-555-0144",
        "email": "maria.santos@example.net",
        "mrn": "3322110",
        "ssn": "321-54-9876",
    },
    {
        "name": "James O'Neill",
        "dob_slash": "01/09/1949",
        "dob_iso": "1949-01-09",
        "addr": "88 Harbor View Road, Seattle, WA 98109",
        "city": "Seattle",
        "phone": "+1-206-555-0177",
        "email": "j.oneill@example.edu",
        "mrn": "A774419",
        "ssn": "111-22-3333",
    },
    {
        "name": "Priya Nair",
        "dob_slash": "09/30/1988",
        "dob_iso": "1988-09-30",
        "addr": "1500 Peachtree Street, Atlanta, GA 30309",
        "city": "Atlanta",
        "phone": "(404) 555-0162",
        "email": "priya.nair@example.org",
        "mrn": "MRN-550012",
        "ssn": "456-78-9012",
    },
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    print(f"  {path.name}: {len(rows)} rows")


def _span(text: str, fragment: str, label: str) -> dict:
    start = text.index(fragment)
    return {"label": label, "start": start, "end": start + len(fragment)}


def _spans_for(text: str, pairs: list[tuple[str, str]]) -> list[dict]:
    return [_span(text, frag, lab) for frag, lab in pairs]


# ---------------------------------------------------------------------------
# False-alarm sets (expect little or no PHI)
# ---------------------------------------------------------------------------


def build_fp_openi(openi_dir: Path, out_dir: Path) -> None:
    rows = []
    for r in iter_reports(openi_dir):
        text = r.body
        if len(text) < 40:
            continue
        rows.append(
            {
                "id": f"openi_{r.id}",
                "text": text,
                "source": "openi",
                "path": str(r.path),
                "expect_phi": False,
            }
        )
    _write_jsonl(out_dir / "fp_openi.jsonl", rows)


def build_fp_tcia(tcia_dir: Path, out_dir: Path) -> None:
    from prototyping.metadata_phi.datasets.tcia_sr import iter_sr_files, load_sr

    rows = []
    for path in iter_sr_files(tcia_dir, limit=None):
        doc = load_sr(path)
        narr = doc.narrative_text.strip()
        if len(narr) < 20:
            continue
        rows.append(
            {
                "id": f"tcia_{doc.path.stem}",
                "text": narr,
                "source": "tcia_sr",
                "path": str(doc.path),
                "expect_phi": False,
            }
        )
    _write_jsonl(out_dir / "fp_tcia_sr.jsonl", rows)


def _iter_rexerr_original(
    rexerr_dir: Path, *, min_chars: int = 80, limit: int | None = None
) -> list[dict[str, str]]:
    """Load unique original_report rows (de-identified MIMIC prose)."""
    csv_paths = sorted(rexerr_dir.rglob("ReXErr-report-level_*.csv"))
    if not csv_paths:
        return []
    # Prefer train → val → test for stable larger pools.
    order = {"train": 0, "val": 1, "test": 2}
    csv_paths.sort(key=lambda p: order.get(p.stem.split("_")[-1], 9))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for csv_path in csv_paths:
        with csv_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                text = (row.get("original_report") or "").strip()
                if len(text) < min_chars:
                    continue
                key = text[:240]
                if key in seen:
                    continue
                seen.add(key)
                sid = str(row.get("study_id") or row.get("subject_id") or len(out))
                out.append({"id": sid, "text": text, "path": str(csv_path)})
                if limit is not None and len(out) >= limit:
                    return out
    return out


def build_fp_rexerr(rexerr_dir: Path, out_dir: Path, *, limit: int = 5000) -> None:
    """Use original_report only (de-identified MIMIC prose)."""
    reports = _iter_rexerr_original(rexerr_dir, limit=limit)
    if not reports:
        print(f"  SKIP ReXErr: no CSVs under {rexerr_dir}")
        return
    rows = [
        {
            "id": f"rexerr_{r['id']}",
            "text": r["text"],
            "source": "rexerr_original",
            "path": r["path"],
            "expect_phi": False,
        }
        for r in reports
    ]
    _write_jsonl(out_dir / "fp_rexerr.jsonl", rows)


def build_fp_radiology_desc(fixtures_en: Path, out_dir: Path) -> None:
    src = fixtures_en / "radiology_negatives.jsonl"
    if not src.is_file():
        print(f"  SKIP radiology negatives: missing {src}")
        return
    rows = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        text = obj.get("text") or ""
        rows.append(
            {
                "id": obj.get("id") or f"radneg_{len(rows)}",
                "text": text,
                "source": "radiology_negatives",
                "expect_phi": False,
            }
        )
    _write_jsonl(out_dir / "fp_radiology_desc.jsonl", rows)


# ---------------------------------------------------------------------------
# Gold: hard (PHI woven into prose, no Patient:/DOB labels)
# ---------------------------------------------------------------------------


def _embed_templates(ident: dict[str, str]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return (sentence, span pairs). No cue words like Patient/DOB/Address/MRN."""
    n, d, a, c = ident["name"], ident["dob_slash"], ident["addr"], ident["city"]
    return [
        (
            f"Compared with imaging from {d} interpreted for {n}, the lungs remain clear.",
            [(d, "DATE"), (n, "NAME")],
        ),
        (
            f"Outside films brought from {a} show no acute process.",
            [(a, "LOCATION")],
        ),
        (
            f"Discussion with {n} confirmed symptoms began after travel through {c}.",
            [(n, "NAME"), (c, "LOCATION")],
        ),
        (
            f"Prior CT dated {ident['dob_iso']} was reviewed; cardiomediastinal silhouette unchanged.",
            [(ident["dob_iso"], "DATE")],
        ),
        (
            f"{n} underwent the examination; no focal consolidation is identified.",
            [(n, "NAME")],
        ),
    ]


def _insert_mid(text: str, sentence: str) -> str:
    """Insert sentence near mid-text, preferring a sentence boundary."""
    cut = max(40, len(text) // 2)
    dot = text.find(". ", cut)
    if 0 <= dot < len(text) - 2:
        cut = dot + 2
    return text[:cut] + sentence + " " + text[cut:]


def build_gold_embedded(openi_dir: Path, out_dir: Path, *, limit: int = 500, seed: int = 42) -> None:
    reports = [r for r in iter_reports(openi_dir) if len(r.findings) >= 80]
    rng = random.Random(seed)
    rng.shuffle(reports)
    rows = []
    for i, r in enumerate(reports[:limit]):
        ident = _IDENTITIES[i % len(_IDENTITIES)]
        templates = _embed_templates(ident)
        sent, pairs = templates[i % len(templates)]
        body = _insert_mid(r.findings, sent)
        text = f"FINDINGS: {body}"
        if r.impression:
            text += f"\nIMPRESSION: {r.impression}"
        spans = _spans_for(text, pairs)
        rows.append(
            {
                "id": f"embed_openi_{r.id}",
                "text": text,
                "spans": spans,
                "source": "openi_embedded",
                "difficulty": "hard",
                "notes": "Fake PHI woven into findings; no Patient/DOB/Address cue labels",
            }
        )
    _write_jsonl(out_dir / "gold_embedded_openi.jsonl", rows)


def build_gold_embedded_rexerr(
    rexerr_dir: Path, out_dir: Path, *, limit: int = 800, seed: int = 11
) -> None:
    """Hard gold: fake PHI woven into ReXErr original_report mid-text."""
    reports = _iter_rexerr_original(rexerr_dir, min_chars=120, limit=max(limit * 2, limit))
    if not reports:
        print(f"  SKIP ReXErr embedded gold: no CSVs under {rexerr_dir}")
        return
    rng = random.Random(seed)
    rng.shuffle(reports)
    rows = []
    for i, r in enumerate(reports[:limit]):
        ident = _IDENTITIES[i % len(_IDENTITIES)]
        templates = _embed_templates(ident)
        sent, pairs = templates[i % len(templates)]
        text = _insert_mid(r["text"], sent)
        rows.append(
            {
                "id": f"embed_rexerr_{r['id']}",
                "text": text,
                "spans": _spans_for(text, pairs),
                "source": "rexerr_embedded",
                "path": r["path"],
                "difficulty": "hard",
                "notes": (
                    "Fake PHI woven into ReXErr original_report; "
                    "no Patient/DOB/Address cue labels"
                ),
            }
        )
    _write_jsonl(out_dir / "gold_embedded_rexerr.jsonl", rows)


def build_gold_cued(openi_dir: Path, out_dir: Path, *, limit: int = 200, seed: int = 7) -> None:
    """Easier tier: labeled header before real findings (cue-word friendly)."""
    reports = [r for r in iter_reports(openi_dir) if len(r.findings) >= 40]
    rng = random.Random(seed)
    rng.shuffle(reports)
    rows = []
    for i, r in enumerate(reports[:limit]):
        ident = _IDENTITIES[i % len(_IDENTITIES)]
        prefix = (
            f"Patient {ident['name']} DOB {ident['dob_slash']}. "
            f"Address {ident['addr']}. "
        )
        text = prefix + f"FINDINGS: {r.findings}"
        if r.impression:
            text += f"\nIMPRESSION: {r.impression}"
        pairs = [
            (ident["name"], "NAME"),
            (ident["dob_slash"], "DATE"),
            (ident["addr"], "LOCATION"),
        ]
        rows.append(
            {
                "id": f"cued_{r.id}",
                "text": text,
                "spans": _spans_for(text, pairs),
                "source": "openi_cued",
                "difficulty": "easy",
                "notes": "Labeled header PHI before real findings",
            }
        )
    _write_jsonl(out_dir / "gold_cued_phi.jsonl", rows)


# ---------------------------------------------------------------------------
# Gold: fixed formats (MRN / phone / email / SSN)
# ---------------------------------------------------------------------------


def build_gold_format(out_dir: Path) -> None:
    rows: list[dict] = []
    templates = [
        ("MRN: {mrn} on the requisition.", [("mrn", "ID")]),
        ("Medical Record {mrn} linked to this study.", [("mrn", "ID")]),
        ("Patient ID {mrn} / phone {phone}.", [("mrn", "ID"), ("phone", "PHONE")]),
        ("Callback number {phone}.", [("phone", "PHONE")]),
        ("Contact {email} for records.", [("email", "EMAIL")]),
        ("SSN {ssn} verified at registration.", [("ssn", "ID")]),
        ("Social Security Number {ssn}.", [("ssn", "ID")]),
        ("Email: {email} Phone: {phone} MRN {mrn}.", [
            ("email", "EMAIL"),
            ("phone", "PHONE"),
            ("mrn", "ID"),
        ]),
    ]
    for i, ident in enumerate(_IDENTITIES):
        for j, (tmpl, keys) in enumerate(templates):
            text = tmpl.format(**ident)
            pairs = [(ident[k], lab) for k, lab in keys]
            rows.append(
                {
                    "id": f"format_{i}_{j}",
                    "text": text,
                    "spans": _spans_for(text, pairs),
                    "source": "synthetic_format",
                    "difficulty": "format",
                    "notes": "Fixed-format identifiers; patterns expected to help",
                }
            )
    _write_jsonl(out_dir / "gold_format_ids.jsonl", rows)


# ---------------------------------------------------------------------------
# Gold: long SR / PDF-style narratives
# ---------------------------------------------------------------------------


def build_gold_long_narrative(out_dir: Path) -> None:
    rows: list[dict] = []
    for i, ident in enumerate(_IDENTITIES):
        # Variant A: cover-sheet style (cues present)
        cover = (
            f"ENCAPSULATED REPORT COVER\n"
            f"Patient Name: {ident['name']}\n"
            f"Date of Birth: {ident['dob_slash']}\n"
            f"MRN: {ident['mrn']}\n"
            f"Phone: {ident['phone']}\n"
            f"Email: {ident['email']}\n"
            f"Home Address: {ident['addr']}\n"
            f"\n"
            f"CLINICAL HISTORY\n"
            f"Adult patient referred for cross-sectional imaging. Prior outside imaging "
            f"was reportedly performed; details are incomplete in the electronic record.\n"
            f"\n"
            f"TECHNIQUE\n"
            f"Multiplanar reconstructions were reviewed. Intravenous contrast was administered "
            f"per protocol when indicated. Dose reduction techniques were applied.\n"
            f"\n"
            f"FINDINGS\n"
            f"The lungs are clear without focal consolidation. No pleural effusion. "
            f"Heart size is within normal limits. No acute osseous abnormality. Soft tissues "
            f"are unremarkable. Visualized upper abdomen is unremarkable on this exam.\n"
            f"\n"
            f"IMPRESSION\n"
            f"No acute cardiopulmonary process.\n"
        )
        pairs_cover = [
            (ident["name"], "NAME"),
            (ident["dob_slash"], "DATE"),
            (ident["mrn"], "ID"),
            (ident["phone"], "PHONE"),
            (ident["email"], "EMAIL"),
            (ident["addr"], "LOCATION"),
        ]
        rows.append(
            {
                "id": f"long_cover_{i}",
                "text": cover,
                "spans": _spans_for(cover, pairs_cover),
                "source": "synthetic_long",
                "difficulty": "long_cued",
                "notes": "Multi-paragraph cover sheet + report body",
            }
        )

        # Variant B: long narrative with mid-text PHI, minimal cues
        narr = (
            f"STRUCTURED REPORT (BASIC TEXT)\n"
            f"\n"
            f"History: Progressive cough. Comparison is made with prior radiographs. "
            f"Referring notes mention coordination of care with {ident['name']} after "
            f"evaluation at {ident['addr']}.\n"
            f"\n"
            f"Procedure: Frontalized and lateral chest radiographs were obtained.\n"
            f"\n"
            f"Findings: The cardiomediastinal silhouette is stable. Lungs are clear. "
            f"No pneumothorax. Osseous structures are intact. Soft tissues are normal. "
            f"A note from {ident['dob_iso']} describes similar findings.\n"
            f"\n"
            f"Impression: No acute cardiopulmonary abnormality. Clinical correlation "
            f"recommended. If symptoms persist, consider further imaging.\n"
            f"\n"
            f"Addendum: Images were reviewed again; impression unchanged. Distribution "
            f"list includes the reading room and the outpatient clinic in {ident['city']}.\n"
        )
        pairs_narr = [
            (ident["name"], "NAME"),
            (ident["addr"], "LOCATION"),
            (ident["dob_iso"], "DATE"),
            (ident["city"], "LOCATION"),
        ]
        rows.append(
            {
                "id": f"long_narr_{i}",
                "text": narr,
                "spans": _spans_for(narr, pairs_narr),
                "source": "synthetic_long",
                "difficulty": "long_hard",
                "notes": "Long SR-like prose; PHI mid-paragraph without Patient:/DOB labels",
            }
        )
    _write_jsonl(out_dir / "gold_long_narrative.jsonl", rows)


# ---------------------------------------------------------------------------
# Gold / FP: DICOM free-text tags (Pseudo-PHI, HEROLIM dose SR)
# ---------------------------------------------------------------------------


# Tags we can auto-label for gold. Comments are included in text as context only.
_DICOM_PHI_TAG_LABELS: dict[str, str] = {
    "PatientName": "NAME",
    "ReferringPhysicianName": "NAME",
    "PerformingPhysicianName": "NAME",
    "OperatorsName": "NAME",
    "RequestingPhysician": "NAME",
    "PatientAddress": "LOCATION",
    "InstitutionName": "LOCATION",
    "InstitutionAddress": "LOCATION",
    "ReferringPhysicianAddress": "LOCATION",
    "PatientBirthDate": "DATE",
    "StudyDate": "DATE",
    "PatientID": "ID",
    "PatientTelephoneNumbers": "PHONE",
}

_CONTEXT_ONLY_TAGS = ("PatientComments", "ImageComments", "StudyDescription", "SeriesDescription")


def _normalize_pn(value: str) -> str:
    """DICOM PN often uses ^ — expose a space form for free-text detectors."""
    return " ".join(p for p in value.replace("^", " ").split() if p)


def _format_dicom_date(value: str) -> str | None:
    v = value.strip()
    if re.fullmatch(r"\d{8}", v):
        return f"{v[0:4]}-{v[4:6]}-{v[6:8]}"
    return None


def _display_tag_value(tag: str, raw: str) -> str:
    if tag.endswith("Name") or tag == "RequestingPhysician":
        return _normalize_pn(raw)
    if tag in {"PatientBirthDate", "StudyDate"}:
        return _format_dicom_date(raw) or raw
    return raw


def _study_tag_rows(
    root: Path,
    *,
    id_prefix: str,
    source: str,
    notes: str,
    include_spans: bool,
) -> list[dict]:
    """One row per StudyInstanceUID from header / comment tags."""
    try:
        import pydicom
    except ImportError:
        print("  SKIP DICOM tag extract: pydicom not installed")
        return []

    by_study: dict[str, dict] = {}
    for path in sorted(root.rglob("*.dcm")):
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        study = str(getattr(ds, "StudyInstanceUID", "") or path.parent.name)
        if study in by_study:
            continue
        fields: list[tuple[str, str, str | None]] = []
        for tag, label in _DICOM_PHI_TAG_LABELS.items():
            if not hasattr(ds, tag):
                continue
            raw = str(getattr(ds, tag)).strip()
            if not raw:
                continue
            fields.append((tag, _display_tag_value(tag, raw), label if include_spans else None))
        for tag in _CONTEXT_ONLY_TAGS:
            if not hasattr(ds, tag):
                continue
            raw = str(getattr(ds, tag)).strip()
            if raw:
                fields.append((tag, raw, None))
        if not fields:
            continue
        lines = [f"{tag}: {disp}" for tag, disp, _ in fields]
        text = "\n".join(lines)
        spans = []
        if include_spans:
            for tag, disp, label in fields:
                if label is None:
                    continue
                frag = f"{tag}: {disp}"
                start = text.index(frag) + len(tag) + 2
                spans.append({"label": label, "start": start, "end": start + len(disp)})
        row: dict = {
            "id": f"{id_prefix}_{study[:20]}",
            "text": text,
            "source": source,
            "path": str(path),
            "difficulty": "dicom_tags",
            "notes": notes,
        }
        if include_spans:
            row["spans"] = spans
        else:
            row["expect_phi"] = False
        by_study[study] = row
    return list(by_study.values())


def build_gold_pseudo_phi(eval_dir: Path, out_dir: Path) -> None:
    if not eval_dir.is_dir():
        print(f"  SKIP Pseudo-PHI Evaluation: missing {eval_dir}")
        return
    rows = _study_tag_rows(
        eval_dir,
        id_prefix="pseudo_eval",
        source="pseudo_phi_eval",
        notes="MIDI-B training Pseudo-PHI Evaluation planted values; one row per study",
        include_spans=True,
    )
    _write_jsonl(out_dir / "gold_pseudo_phi_tags.jsonl", rows)


def build_fp_pseudo_phi_deid(deid_dir: Path, out_dir: Path) -> None:
    """De-identified Pseudo-PHI side — detectors should not invent patient PHI."""
    if not deid_dir.is_dir():
        print(f"  SKIP Pseudo-PHI DeIdentified: missing {deid_dir}")
        return
    rows = _study_tag_rows(
        deid_dir,
        id_prefix="pseudo_deid",
        source="pseudo_phi_deid",
        notes="Pseudo-PHI DeIdentified side; research IDs only — false-alarm check",
        include_spans=False,
    )
    _write_jsonl(out_dir / "fp_pseudo_phi_deid.jsonl", rows)


def build_herolim_sr(herolim_dir: Path, out_dir: Path) -> None:
    """Real-world radiation dose SR: header PHI gold + protocol-text false-alarm set.

    Contains real patient identifiers. Output stays under local corpus/ (gitignored).
    """
    if not herolim_dir.is_dir():
        print(f"  SKIP HEROLIM SR: missing {herolim_dir}")
        return
    try:
        import pydicom
    except ImportError:
        print("  SKIP HEROLIM SR: pydicom not installed")
        return

    gold_rows = _study_tag_rows(
        herolim_dir,
        id_prefix="herolim",
        source="herolim_dose_sr",
        notes="Real radiation dose SR headers (local PHI — do not commit)",
        include_spans=True,
    )
    _write_jsonl(out_dir / "gold_herolim_sr_tags.jsonl", gold_rows)

    # Protocol / device strings from ContentSequence — should not look like patient names.
    from prototyping.metadata_phi.datasets.tcia_sr import load_sr

    fp_rows = []
    for path in sorted(herolim_dir.rglob("*.dcm")):
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        if str(getattr(ds, "Modality", "")) != "SR":
            continue
        doc = load_sr(path)
        # Narrative helper keeps TextValue / descriptions; dose SR mostly coded.
        # Prefer raw TextValue-like chunks and protocol-ish strings only.
        parts = []
        for c in doc.chunks:
            if c.tag_or_path in {
                "PatientName",
                "PatientID",
                "InstitutionName",
                "InstitutionAddress",
                "ReferringPhysicianName",
                "PerformingPhysicianName",
                "PatientBirthDate",
                "StudyDate",
            }:
                continue
            if "TextValue" in c.tag_or_path or c.tag_or_path in {
                "StudyDescription",
                "SeriesDescription",
            }:
                parts.append(c.text)
            elif c.tag_or_path.endswith("CodeMeaning") and len(c.text) >= 12:
                # Acquisition protocol names, etc.
                if c.text.lower() not in {"person", "device", "procedure"}:
                    parts.append(c.text)
        text = "\n".join(parts).strip()
        if len(text) < 8:
            continue
        fp_rows.append(
            {
                "id": f"herolim_proto_{path.stem[:24]}",
                "text": text,
                "source": "herolim_dose_sr_protocol",
                "path": str(path),
                "expect_phi": False,
                "notes": "Dose SR protocol/device text without patient header tags",
            }
        )
    _write_jsonl(out_dir / "fp_herolim_sr_protocol.jsonl", fp_rows)


def build_midi_b_heldout(midi_dir: Path, heldout_dir: Path) -> None:
    """Reserve MIDI-B 2024 VAL for the final prototype test (not method selection).

    The local tree is the small de-identified validation image set + ID mappings.
    """
    if not midi_dir.is_dir():
        print(f"  SKIP MIDI-B VAL: missing {midi_dir}")
        return
    out = heldout_dir / "midi_b_2024_val"
    out.mkdir(parents=True, exist_ok=True)
    rows = _study_tag_rows(
        midi_dir / "data" if (midi_dir / "data").is_dir() else midi_dir,
        id_prefix="midi_b_val",
        source="midi_b_2024_val",
        notes=(
            "HELD OUT — NIH MIDI-B 2024 validation images (de-id IDs in this tree). "
            "Do not use while choosing detectors; run as final prototype test."
        ),
        include_spans=False,
    )
    _write_jsonl(out / "fp_midi_b_val_tags.jsonl", rows)

    # Keep mapping paths discoverable next to the held-out extract.
    map_dir = midi_dir / "mappings"
    mapping_note = {
        "role": "heldout_final_test",
        "source_dir": str(midi_dir),
        "patient_id_mapping": str(map_dir / "patient_id_mapping.csv"),
        "uid_mapping": str(map_dir / "uid_mapping.csv"),
        "n_studies_extracted": len(rows),
        "warning": (
            "This folder is reserved for the definitive MIDI-B-style test after "
            "the prototype is chosen. Development scoring must not train or tune on it."
        ),
    }
    (out / "README.json").write_text(json.dumps(mapping_note, indent=2) + "\n", encoding="utf-8")
    print(f"  MIDI-B held-out → {out} ({len(rows)} studies)")


def build_tcia_date_gold(tcia_dir: Path, out_dir: Path) -> None:
    from prototyping.metadata_phi.datasets.tcia_sr import iter_sr_files, load_sr

    rows = []
    for path in iter_sr_files(tcia_dir, limit=None):
        doc = load_sr(path)
        narr = doc.narrative_text
        dates = list(_DATE_ISO.finditer(narr))
        if not dates:
            continue
        rows.append(
            {
                "id": f"tcia_date_{doc.path.stem}",
                "text": narr,
                "spans": [{"label": "DATE", "start": m.start(), "end": m.end()} for m in dates],
                "source": "tcia_sr",
                "difficulty": "date_in_sr",
                "notes": "Calendar dates remaining in TCIA SR narrative",
            }
        )
    _write_jsonl(out_dir / "gold_tcia_dates.jsonl", rows)


def write_manifest(out_dir: Path) -> None:
    lines = [
        "# Eval corpus manifest",
        "",
        "Built for comparing pattern-based vs context-based detectors fairly.",
        "",
        "| File | Role |",
        "| --- | --- |",
    ]
    for path in sorted(out_dir.glob("*.jsonl")):
        n = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        lines.append(f"| `{path.name}` | {n} rows |")
    (out_dir / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  MANIFEST.md written")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, default=_CORPUS)
    p.add_argument("--heldout-dir", type=Path, default=_HELDOUT)
    p.add_argument("--openi-dir", type=Path, default=Path(DEFAULT_OPENI_DIR))
    p.add_argument("--tcia-dir", type=Path, default=Path(DEFAULT_TCIA_SR_DIR))
    p.add_argument("--rexerr-dir", type=Path, default=Path(DEFAULT_REXERR_DIR))
    p.add_argument("--pseudo-phi-eval-dir", type=Path, default=Path(DEFAULT_PSEUDO_PHI_EVAL_DIR))
    p.add_argument("--pseudo-phi-deid-dir", type=Path, default=Path(DEFAULT_PSEUDO_PHI_DEID_DIR))
    p.add_argument("--herolim-dir", type=Path, default=Path(DEFAULT_HEROLIM_SR_DIR))
    p.add_argument("--midi-b-dir", type=Path, default=Path(DEFAULT_MIDI_B_VAL_DIR))
    p.add_argument("--embedded-limit", type=int, default=500)
    p.add_argument("--embedded-rexerr-limit", type=int, default=800)
    p.add_argument("--cued-limit", type=int, default=200)
    p.add_argument("--rexerr-fp-limit", type=int, default=5000)
    # Backward-compatible alias used by older CLI wiring.
    p.add_argument("--pseudo-phi-dir", type=Path, default=None)
    args = p.parse_args(argv)

    fixtures_en = Path(__file__).resolve().parents[1] / "fixtures" / "en_US"
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    print(f"Building eval corpus → {out}")

    print("False-alarm sets")
    if args.openi_dir.is_dir():
        build_fp_openi(args.openi_dir, out)
    else:
        print(f"  SKIP Open-i: {args.openi_dir}")
    if args.tcia_dir.is_dir():
        build_fp_tcia(args.tcia_dir, out)
        build_tcia_date_gold(args.tcia_dir, out)
    else:
        print(f"  SKIP TCIA: {args.tcia_dir}")
    build_fp_rexerr(args.rexerr_dir, out, limit=args.rexerr_fp_limit)
    build_fp_radiology_desc(fixtures_en, out)
    build_fp_pseudo_phi_deid(args.pseudo_phi_deid_dir, out)

    print("Gold sets")
    if args.openi_dir.is_dir():
        build_gold_embedded(args.openi_dir, out, limit=args.embedded_limit)
        build_gold_cued(args.openi_dir, out, limit=args.cued_limit)
    build_gold_embedded_rexerr(
        args.rexerr_dir, out, limit=args.embedded_rexerr_limit
    )
    build_gold_format(out)
    build_gold_long_narrative(out)
    eval_dir = args.pseudo_phi_dir or args.pseudo_phi_eval_dir
    build_gold_pseudo_phi(eval_dir, out)
    build_herolim_sr(args.herolim_dir, out)

    print("Held-out final test (not for method selection)")
    build_midi_b_heldout(args.midi_b_dir, args.heldout_dir)

    write_manifest(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
