# De-identification protocol

This page summarizes how the Anonymizer follows the DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)) in plain language. The formal § E.1.3 response for reviewers is the [DICOM Conformance Statement](dicom-conformance-statement.md).

## HIPAA Safe Harbor and MIDI-B {#hipaa-safe-harbor-and-midi-b}

US sites often ask about **HIPAA Safe Harbor**. That rule is a **de-identification method** under the Privacy Rule (remove listed identifier categories, with no actual knowledge of re-identification)—not a product certification from HHS. The Anonymizer does **not** claim to be “HIPAA certified” or “Safe Harbor compliant” as software.

What we *do* claim:

- The default ingest path implements DICOM PS 3.15 confidentiality options (Basic Profile and the retain options you select).
- Those options, and the public **MIDI-B** answer key / official scorer used in testing, are designed around **Safe Harbor–style** removal of imaging identifiers plus TCIA-style research metadata practices.
- Default **date shifting** keeps longitudinal spacing (Modified Dates). That is **not** the same as Safe Harbor’s year-only date rule. Sites that need year-only (or Expert Determination) must set policy with their privacy officer.
- Pixel text, report prose, and faces still need the optional AI / Report Text Review steps when those objects are present.

Use MIDI-B scores and this protocol as **evidence for review**, not as a substitute for institutional determination.

## De-identification options (ingest)

Ingest uses the **anonymizer script only** (never NER/OCR). Project Settings choose **de-identification options** — the DICOM confidentiality options of [PS 3.15 Table E.1-1](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) — shown by their standard names (Basic Profile, Retain Longitudinal Temporal Information Modified Dates Option, …). Two preset buttons fill the checkbox set: **Basic** (Basic Profile only) and **Retain** (Basic Profile + Modified Dates + Patient Characteristics + Retain Safe Private). Presets store nothing; the project stores only the selected option codes.

The script is **compiled** from the selected options using the packaged `default-anonymizer.script` plus option overlays, and stored beside `ProjectModel.json` as `{site_id}-anonymizer.script`. A project carries **one date strategy**: every date rule must match the StudyDate rule's operation (the script editor offers a one-click fix). A custom CTP script can be imported from the script editor; unknown operands reject the import, date rules must match StudyDate, and the options recorded for it are the ones you confirm (prefilled from the script's rules). The project records whether its script was generated or imported (filename + SHA-256).

Private tags at ingest depend on **Retain Safe Private**:

- Without it, **all private tags are removed** before the walk.
- With it, private elements are resolved **in the anonymize walk** from the TCIA Private Tag KB (generated lookup dict, matched by private creator): keep / remove / UID-remap / date delta by the project date delta; unknown slots are removed and logged. Retain Safe Private needs your own knowledge of which private tags are safe — the KB is the project's action source; the anonymizer log records one line per unknown private element removed (tag, creator, VR — never values).

Executed options are recorded in `(0012,0064) DeidentificationMethodCodeSequence`: ingest records the selected options that run at ingest; later tasks record theirs when they run (Clean Pixel Data 113101 by Remove Burnt-in Text, Retain Safe Private 113111 at ingest, Clean Structured Content 113104 by report cleaning, Clean Descriptors 113105 by metadata cleaning, Clean Recognizable Visual Features 113102 by Blur Face). Clean Graphics (113103) is selectable but not executed yet — non-text burned-in graphics are uncommon/legacy after curve and overlay removal at import; see [DICOM Conformance Statement](dicom-conformance-statement.md#why-clean-graphics-is-not-executed). Selecting Clean Structured Content or Clean Descriptors enables SR/PDF modalities; newly enabling SR or PDF modalities enables Clean Structured Content when it is off. Clean Structured Content also **keeps** Encapsulated Document bytes and SR content-text tags at import so Report Text Review / AI Batch can scrub them afterward (Basic alone removes those tags).

## What gets removed or replaced

Under the Basic Profile at import:

- All private tags are removed; curve and overlay groups are removed.
- Patient Name and Patient ID become the site ID plus a sequential patient number that stays the same for that person in the project.
- Accession Number, Study/Series/Instance UIDs, and dates (`@hashdate`) are replaced with **deterministic** project-scoped values so links between images stay consistent. See [Deterministic replacements](#deterministic-replacements-uids-dates-accessions) below.
- Birth date, physician names, institution identity, device identity, and patient characteristics are removed; Patient Age is rounded to a five-year band.
- The file sets Patient Identity Removed to YES, names the RSNA DICOM Anonymizer as the method, and lists active option codes in Deidentification Method Code Sequence.

## Deterministic replacements (UIDs, dates, accessions) {#deterministic-replacements-uids-dates-accessions}

These transforms are **intentional** and **secret-free**. Their job is **stable linkage within a project** (and a matching row in the project PHI/UID tables)—not keyed unlinkability against someone who already knows a candidate original value.

| Value | How it is derived | What that means |
| --- | --- | --- |
| **DICOM UIDs** | Project prefix (`uid_root` + site id) + truncated MD5 of the original UID | Same original → same anon UID. Anyone who can **guess** an original UID can compute the replacement and compare. You cannot usefully **invert** an anon UID back to an unknown original from the anonymized file alone. |
| **Dates (`@hashdate`)** | Day offset from MD5 of Patient ID (mod ~10 years) | Same patient → same offset; intervals between that patient’s studies stay meaningful. |
| **Accession number** | SHA-256 of a **project mixer** string (`site_id` / `uid_root`) plus the original accession | Different projects produce different hashes for the same accession (useful). The mixer is **not** a secret key: site id and UID root appear in released anonymized UIDs, so someone holding released data can rebuild it and verify guessed accessions. |

**Not claimed:** cryptographic resistance to online verification when the attacker already has a plausible original UID, Patient ID, or accession (for example a predictable org-root + counter pattern). That is expected for public, deterministic constructions and is common among open DICOM de-identifiers.

**Do claim:** originals are not stored in the released DICOM; the authoritative map lives in the project private database—keep that database out of export/send packages.

## Dates

Dates are shifted so the **order and spacing** of a patient’s studies stay meaningful, but calendar dates are not the originals. Time-of-day is typically left as-is. Strategies (script / lookup):

- **@hashdate** — per-patient deterministic offset (default packaged script)
- **@lookup(this,dateoffset)** — per-patient offset from a CTP `.properties` table
- **@incrementdate(this,n)** — fixed trial-wide day offset (CTP DATEINC; packaged default offset in `controller/private_tags/dateinc.txt`). Private date elements under Retain Safe Private shift by the same single resolved delta as public dates.
- **@rebasedate(this,origin)** — epoch rebase from registration `basedate/` + ORIGIN parameter (default `19600101`)

When any of these run, the anonymizer writes `(0028,0303) LongitudinalTemporalInformationModified = MODIFIED`, and records code 113107 when the Modified Dates option is selected. See [Create project — longitudinal dates](05-create-project/index.md#longitudinal-dates-tcia-style).

## What may be kept (partial options)

Examples of retained clinical context (depending on script / profile options):

- Study and Series descriptions (you may later standardize series names with Harmonize)
- Sex, age, size, weight, and similar characteristics when **Retain Patient Characteristics** is selected (removed under Basic)
- Manufacturer, model, serial, station, and related device tags when **Retain Device Identity** is selected (removed under Basic)

## Pixel and face options in the DICOM profile

The classic profile options “clean pixel data” and “clean recognizable visual features” are **not** claimed as automatic DICOM profile bits alone. Use optional **Embedded PHI** (OCR + English NER) after ingest instead:

- [Embedded PHI / burnt-in text](08-process/02-remove-burned-in-text/index.md) — Series View for pixels; Report Text Review for SR/PDF (Blank or Synthetic hide-in-plain-sight)
- [Blur faces](08-process/04-blur-faces/index.md)

Capture stores **removed PHI entity text only** (`EmbeddedPHI` / `EmbeddedPHIRemoved`), never full report transcripts.

## Structured reports and overlays

Curve/overlay groups are removed. Whether Structured Report / Encapsulated PDF objects are accepted is controlled by project modalities; selecting Clean Structured Content or Clean Descriptors enables SR/PDF, and selecting SR or PDF enables Clean Structured Content.

!!! note "For compliance review"
    Have your privacy officer review the [de-identification options](05-create-project/index.md#2-de-identification-options) and any [custom script edits](05-create-project/index.md#4-custom-script-edits), plus AI tools for your institution. See also the [DICOM Conformance Statement](dicom-conformance-statement.md) and [HIPAA Safe Harbor and MIDI-B](#hipaa-safe-harbor-and-midi-b). This manual is operational guidance, not legal advice.
