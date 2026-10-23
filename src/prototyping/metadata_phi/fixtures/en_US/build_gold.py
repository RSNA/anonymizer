"""Build English gold JSONL sets with verified character offsets.

Writes:
  - gold.jsonl       — deep eval set (default for CLI eval)
  - gold_smoke.jsonl — small sanity set from the first prototype
"""

import json
from pathlib import Path


def _span(text: str, fragment: str, label: str, *, occurrence: int = 0) -> dict:
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(fragment, start + 1)
    return {"label": label, "start": start, "end": start + len(fragment)}


def _add(
    rows: list[dict],
    eid: str,
    text: str,
    frags: list[tuple[str, str] | tuple[str, str, int]],
    notes: str = "",
) -> None:
    spans = []
    for item in frags:
        if len(item) == 3:
            frag, lab, occ = item  # type: ignore[misc]
            spans.append(_span(text, frag, lab, occurrence=int(occ)))
        else:
            frag, lab = item  # type: ignore[misc]
            spans.append(_span(text, frag, lab))
    rows.append({"id": eid, "text": text, "spans": spans, "notes": notes})


def smoke_examples() -> list[dict]:
    rows: list[dict] = []
    _add(
        rows,
        "tp_report_header",
        "Patient Jane Doe DOB 03/14/1962 lives at 12 Oak Street, Boston, MA 02108. "
        "MRN: 4455667 Phone: (555) 123-4567 Email: jane.doe@example.org SSN: 123-45-6789",
        [
            ("Jane Doe", "NAME"),
            ("03/14/1962", "DATE"),
            ("12 Oak Street, Boston, MA 02108", "LOCATION"),
            ("4455667", "ID"),
            ("(555) 123-4567", "PHONE"),
            ("jane.doe@example.org", "EMAIL"),
            ("123-45-6789", "ID"),
        ],
        "mixed true positives",
    )
    _add(
        rows,
        "tp_mrn_variants",
        "Medical Record 998877 Patient ID ABC-12345 Acct # 77721 Visit ID 9001 Accession ACC998877",
        [
            ("998877", "ID"),
            ("ABC-12345", "ID"),
            ("77721", "ID"),
            ("9001", "ID"),
            ("ACC998877", "ID"),
        ],
        "MRN / account / visit / accession cues",
    )
    _add(
        rows,
        "tp_ssn_bare",
        "Social Security Number 987654321 on file.",
        [("987654321", "ID")],
        "9-digit SSN with cue",
    )
    _add(
        rows,
        "tp_physician",
        "Referring physician Dr. Alice Smith requested the exam.",
        [("Alice Smith", "NAME")],
        "physician name",
    )
    _add(rows, "hn_mr_breast", "MR BREAST BILATERAL WITH AND WITHOUT CONTRAST", [], "hard negative")
    _add(rows, "hn_ct_cap", "CT CHEST ABDOMEN PELVIS", [], "hard negative")
    _add(rows, "hn_portable", "PORTABLE AP CHEST", [], "hard negative")
    _add(
        rows,
        "hn_protocol_series",
        "Protocol 12 Series 3 Instance 7 kVp 120 UID 1.2.840.113619.2.55.3.2831166119.567",
        [],
        "hard negative: protocol/UID",
    )
    _add(rows, "amb_smith_protocol", "SMITH PROTOCOL T1 AXIAL", [], "ambiguous protocol name")
    _add(
        rows,
        "amb_washington",
        "Performed at Washington Hospital Center campus.",
        [("Washington Hospital Center campus", "LOCATION")],
        "facility as location",
    )
    _add(rows, "amb_id_series", "ID 3 is the sagittal series.", [], "series id not patient id")
    _add(
        rows,
        "tp_phone_intl",
        "Call patient at +1 555 987 6543 ext. 12 regarding results.",
        [("+1 555 987 6543 ext. 12", "PHONE")],
        "intl phone + extension",
    )
    return rows


def deep_examples() -> list[dict]:
    """Richer SR/PDF-like paragraphs + harder radiology negatives."""
    rows = list(smoke_examples())

    # --- Long structured-report style narrative ---
    sr = (
        "RADIOLOGY REPORT\n"
        "Exam: MR BREAST BILATERAL WITH AND WITHOUT CONTRAST\n"
        "Patient: Mary Anne Cooper  DOB: 07/22/1975  MRN: MRN784512\n"
        "Address: 4821 Willow Creek Drive, Austin, TX 78745\n"
        "Phone: 512-555-0198  Fax: (512) 555-0199\n"
        "Email: m.cooper@email.example\n"
        "SSN: 321-54-9876  Account #: 90817263\n"
        "Ordering: Dr. Robert Chen\n"
        "Clinical history: Screening. Prior outside films from Metro General Hospital.\n"
        "Technique: Axial T1, T2, DWI. Protocol 14. Series 6. Slice thickness 3 mm. kVp n/a.\n"
        "Findings: No suspicious mass. Left breast BI-RADS 2.\n"
        "Impression: Benign. Recommend routine screening.\n"
        "Electronically signed by Dr. Robert Chen on 2024-11-03."
    )
    _add(
        rows,
        "sr_breast_full",
        sr,
        [
            ("Mary Anne Cooper", "NAME"),
            ("07/22/1975", "DATE"),
            ("MRN784512", "ID"),
            ("4821 Willow Creek Drive, Austin, TX 78745", "LOCATION"),
            ("512-555-0198", "PHONE"),
            ("(512) 555-0199", "PHONE"),
            ("m.cooper@email.example", "EMAIL"),
            ("321-54-9876", "ID"),
            ("90817263", "ID"),
            ("Robert Chen", "NAME"),
            ("Metro General Hospital", "LOCATION"),
            ("Robert Chen", "NAME", 1),
            ("2024-11-03", "DATE"),
        ],
        "full SR-style report; anatomy lines must not become NAME",
    )

    # --- CT chest report with accession in narrative ---
    ct = (
        "CT CHEST ABDOMEN PELVIS WITH CONTRAST performed for staging.\n"
        "Patient John Q. Public, DOB 1/5/1950, Patient ID 55-90210, Accession ACC20241105001.\n"
        "Lives at 9 Elm St, Portland, OR 97201. Contact 503.555.4411.\n"
        "Comparison: prior CT dated 03/01/2023.\n"
        "Findings: No acute PE. Liver lesions unchanged. Series 2, Series 7 reformats.\n"
        "Dictated by Dr. Elena Vargas."
    )
    _add(
        rows,
        "sr_ct_cap_staging",
        ct,
        [
            ("John Q. Public", "NAME"),
            ("1/5/1950", "DATE"),
            ("55-90210", "ID"),
            ("ACC20241105001", "ID"),
            ("9 Elm St, Portland, OR 97201", "LOCATION"),
            ("503.555.4411", "PHONE"),
            ("03/01/2023", "DATE"),
            ("Elena Vargas", "NAME"),
        ],
        "CT CAP narrative with accession + address",
    )

    # --- Encapsulated PDF cover-sheet style ---
    pdf = (
        "CONFIDENTIAL PATIENT SUMMARY\n"
        "Name: Samuel Wright\n"
        "DOB: 1962-08-19\n"
        "MRN 00445566\n"
        "SSN 111223333\n"
        "Home: 2200 Market Street, Suite 400, Philadelphia, PA 19103\n"
        "Mobile +1 215 555 7788\n"
        "Email samuel.wright@patients.example.org\n"
        "Visit ID VIS-88991  Encounter 441122\n"
        "Attached imaging: PORTABLE AP CHEST; CT CHEST WITHOUT CONTRAST.\n"
        "Device UID 1.2.840.113619.2.55.3.604688432.781.1234567890.1 is not a patient id."
    )
    _add(
        rows,
        "pdf_cover_sheet",
        pdf,
        [
            ("Samuel Wright", "NAME"),
            ("1962-08-19", "DATE"),
            ("00445566", "ID"),
            ("111223333", "ID"),
            ("2200 Market Street, Suite 400, Philadelphia, PA 19103", "LOCATION"),
            ("+1 215 555 7788", "PHONE"),
            ("samuel.wright@patients.example.org", "EMAIL"),
            ("VIS-88991", "ID"),
            ("441122", "ID"),
        ],
        "PDF cover sheet; UID line must not score as ID/PHONE",
    )

    # --- Ambiguous / hard negatives mixed into prose ---
    _add(
        rows,
        "hn_technique_block",
        "Technique: 120 kVp, 200 mAs, Protocol 9, Series 12, Instance 144, Station ID CT01.",
        [],
        "technique block — no PHI",
    )
    _add(
        rows,
        "hn_birads_anatomy",
        "Right breast BI-RADS 1. Left breast BI-RADS 2. No suspicious enhancement.",
        [],
        "laterality/anatomy not LOCATION/NAME",
    )
    _add(
        rows,
        "hn_view_codes",
        "XR KNEE 3 VIEWS RIGHT. PA and LAT obtained. OBLIQUE additional view.",
        [],
        "view codes",
    )
    _add(
        rows,
        "amb_doctor_vs_drive",
        "Patient lives at 77 Doctor Drive near the clinic campus entrance.",
        [("77 Doctor Drive", "LOCATION")],
        "street named Doctor — LOCATION not NAME",
    )
    _add(
        rows,
        "tp_chart_unit",
        "Unit Number UN-55221 Chart Number CH9981 Med Rec # 334455",
        [
            ("UN-55221", "ID"),
            ("CH9981", "ID"),
            ("334455", "ID"),
        ],
        "unit/chart/med-rec cue variants",
    )
    _add(
        rows,
        "tp_fin_encounter",
        "FIN 88776655 Encounter # E-100200 Medicare ID MCD9988771",
        [
            ("88776655", "ID"),
            ("E-100200", "ID"),
            ("MCD9988771", "ID"),
        ],
        "FIN / encounter / medicare-style id",
    )
    _add(
        rows,
        "tp_dob_spoken",
        "Date of birth November 3, 1988. Study date 20241105.",
        [
            ("November 3, 1988", "DATE"),
            ("20241105", "DATE"),
        ],
        "month-name DOB + DICOM DA",
    )
    _add(
        rows,
        "tp_two_patients_note",
        "Addendum: compared with sister case for Patient Helen Park MRN: 1212121; "
        "current subject remains Patient Jose Alvarez MRN: 3434343.",
        [
            ("Helen Park", "NAME"),
            ("1212121", "ID"),
            ("Jose Alvarez", "NAME"),
            ("3434343", "ID"),
        ],
        "two named patients in one note",
    )
    _add(
        rows,
        "hn_smith_sequence",
        "SMITH PROTOCOL coronal T2; not a physician name reference.",
        [],
        "protocol eponym without Dr/Patient cue",
    )
    _add(
        rows,
        "tp_email_phone_footer",
        "Questions: call (800) 555-0100 or email imaging-desk@hospital.example.",
        [
            ("(800) 555-0100", "PHONE"),
            ("imaging-desk@hospital.example", "EMAIL"),
        ],
        "contact footer",
    )
    _add(
        rows,
        "amb_washington_city",
        "Patient relocated to Washington, DC 20001 last year.",
        [("Washington, DC 20001", "LOCATION")],
        "city/state/zip LOCATION",
    )
    _add(
        rows,
        "hn_id_frame",
        "ID # 2 corresponds to the arterial phase series, not a medical record number.",
        [],
        "short ID# series reference — prefer no ID",
    )
    return rows


def radiology_negatives() -> list[str]:
    return [
        "MR BREAST BILATERAL WITH AND WITHOUT CONTRAST",
        "MRI BREAST UNILATERAL RIGHT WITH CONTRAST",
        "CT CHEST ABDOMEN PELVIS",
        "CT CHEST ABDOMEN PELVIS WITH CONTRAST",
        "CT CHEST WITHOUT CONTRAST",
        "PORTABLE AP CHEST",
        "PA AND LATERAL CHEST",
        "XR KNEE 3 VIEWS RIGHT",
        "XR ANKLE 2 VIEWS LEFT",
        "US ABDOMEN COMPLETE",
        "US PELVIS TRANSVAGINAL",
        "MRI BRAIN WITH AND WITHOUT CONTRAST",
        "MR LUMBAR SPINE WITHOUT CONTRAST",
        "CT HEAD WITHOUT CONTRAST",
        "PET CT SKULL BASE TO MID THIGH",
        "NM BONE SCAN WHOLE BODY",
        "MG SCREENING BILATERAL",
        "Protocol 12 Series 3",
        "Protocol 9 Series 12 Instance 144",
        "T1 AXIAL POST CONTRAST",
        "T2 SAGITTAL FS",
        "DWI B1000 AXIAL",
        "MIP CORONAL REFORMAT",
        "LOCALIZER",
        "SCOUT",
        "TOPOGRAM",
        "SMITH PROTOCOL T1 AXIAL",
        "120 kVp 200 mAs",
        "Slice thickness 3 mm",
        "Right breast BI-RADS 1",
        "Left breast BI-RADS 2",
        "No acute cardiopulmonary process",
        "UID 1.2.840.113619.2.55.3.2831166119.567",
    ]


def main() -> None:
    root = Path(__file__).parent
    deep = deep_examples()
    smoke = smoke_examples()
    (root / "gold.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in deep) + "\n", encoding="utf-8"
    )
    (root / "gold_smoke.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in smoke) + "\n", encoding="utf-8"
    )
    (root / "radiology_negatives.jsonl").write_text(
        "\n".join(json.dumps({"text": t}, ensure_ascii=False) for t in radiology_negatives()) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(deep)} deep examples → gold.jsonl")
    print(f"Wrote {len(smoke)} smoke examples → gold_smoke.jsonl")
    print(f"Wrote {len(radiology_negatives())} radiology negatives")


if __name__ == "__main__":
    main()
