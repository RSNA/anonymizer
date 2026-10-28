# DICOM Conformance Statement

This page is the product’s response to [DICOM PS 3.15 § E.1.3 Conformance Requirements](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/sect_E.1.3.html) for applications that claim the **Basic Application Level Confidentiality Profile**.

It is written for privacy officers and reviewers. Day-to-day workflow lives in the [De-identification protocol](deidentification-protocol.md) and [Create a project](05-create-project/index.md#2-de-identification-options).

!!! note "Scope of this claim"
    Conformance here means the **ingest path** implements the Basic Profile (and selected Appendix E options) by applying the project anonymizer script to DICOM attributes. Optional pixel, report, descriptor, and face cleaning run **after** import when those options and AI features are enabled. This statement is not legal advice and is not a HIPAA product certification — see [HIPAA Safe Harbor and MIDI-B](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b).

## Profile and options claimed

| Item | Claim |
| --- | --- |
| Profile | **Basic Application Level Confidentiality Profile** (CID 7050 code 113100) |
| Attribute catalog | [PS 3.15 Table E.1-1](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) — packaged extract `e1_1_retain_tags.json` drives retain-option compile overlays |
| Method stamps | `(0012,0062) Patient Identity Removed = YES`; `(0012,0063) Deidentification Method = RSNA DICOM ANONYMIZER`; selected option codes in `(0012,0064) Deidentification Method Code Sequence` |
| Authoritative per-project rules | Compiled `{site_id}-anonymizer.script` beside `ProjectModel.json` (from packaged `default-anonymizer.script` plus option overlays, or an imported custom script) |

## E.1.3 checklist

### Which Attributes are removed during protection

Under the **Basic Profile** at import (default packaged script, unless a retain option or custom edit keeps them):

- **All private tags** (unless **Retain Safe Private** is selected — then each private element is resolved from the TCIA private-tag knowledge base; unknown slots are removed).
- **Curve and overlay groups**.
- Attributes Table E.1-1 marks for removal or blanking under Basic that the project script implements with `@remove()`, `@empty()`, or equivalent (birth date, physician names, institution identity, device identity, patient characteristics, and many clinical workflow identifiers).
- **Encrypted Attributes** sequence and related encryption tags (`Encrypted Attributes Sequence`, `Encrypted Content`, `Encrypted Content Transfer Syntax UID`, and related Group 0400 signature / encryption elements) — **removed**, not populated.
- Digital signature UIDs and related signature elements — **removed**.

The **complete** remove/keep/transform list for a given project is the project’s compiled anonymizer script (Anonymizer Script Editor). Retain options change overlays as described in [De-identification options](05-create-project/index.md#2-de-identification-options). Custom script edits override compile for those tags until options are re-accepted (which recompiles from the packaged default and **drops** custom edits).

### Which Attributes are replaced by dummy values and how they are generated

| Attribute class | How replacement values are generated |
| --- | --- |
| **Patient Name / Patient ID** | Site ID plus a sequential patient number that stays the same for that person **in this project** (lookup in the project private database). |
| **Accession Number** | Deterministic hash of a project mixer (`site_id` / `uid_root`) plus the original accession. |
| **DICOM UIDs** (Study, Series, SOP Instance, Frame of Reference, and other script rules with `@uid`) | Project prefix (`uid_root` + site id) + truncated MD5 of the original UID — same original → same replacement **within the project**. |
| **Dates / DateTimes** (script date-delta operands) | Per-patient or trial strategy: default `@hashdate` (day offset from Patient ID); or `@lookup`, `@incrementdate`, `@rebasedate` when configured. Time-of-day is typically left unchanged. See [Dates](deidentification-protocol.md#dates). |
| **Patient Age** | Rounded to a five-year band (`@round`) even when **Retain Patient Characteristics** is selected. |
| **Other Basic blanks** | `@empty()` or fixed literals where the script specifies them. |

Details and security caveats: [Deterministic replacements](deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

**Retain UIDs** (when selected) keeps original UIDs instead of `@uid` remapping. **Full Dates** keeps original calendar dates instead of shifting them.

### Encrypted Attributes Data Sets (re-identification)

**Not supported.** The Anonymizer does **not** place originals into an Encrypted Attributes Data Set for later re-identification, and it does **not** select encryption keys for that purpose.

- Default script **removes** Encrypted Attributes Sequence / Encrypted Content / related Group 0400 encryption tags if present.
- The authoritative original↔anonymous map (patient IDs, UIDs, etc.) lives in the **project private database**, which must stay out of export/Send packages — not in the released DICOM objects.

### Scope of referential integrity for replacement values

| Scope | Behavior |
| --- | --- |
| **Within one project** | Same original Patient ID, Accession, or UID → same anonymized value for every SOP Instance processed in that project (stable linkage across Studies, Series, and instances already in the project store). |
| **Frame of Reference and related UIDs** | Script `@uid` rules (e.g. Frame of Reference UID) remapped consistently with other UIDs when **Retain UIDs** is off. Some radiotherapy / reference sequences are removed under Basic rather than remapped — see the project script. |
| **Re-processing the same Study** | Re-import into the **same** project reuses stored PHI/UID mappings where the originals match. Recompiling options does **not** rewrite already-stored files. |
| **Across projects** | **Not** guaranteed. Different `site_id` / `uid_root` / patient counters produce different replacements. |
| **Across sites sharing only released DICOM** | Replacement UIDs/accessions are **secret-free** constructions; see the deterministic-replacements caveats. |

### Which Attributes and Attribute Values are inserted during protection

At successful import protection, the product ensures at least:

| Tag | Value / behavior |
| --- | --- |
| `(0012,0062) Patient Identity Removed` | `YES` (created via `@always()` if absent) |
| `(0012,0063) Deidentification Method` | `RSNA DICOM ANONYMIZER` |
| `(0012,0064) Deidentification Method Code Sequence` | One DCM item per **executed** option code (ingest options at import; cleaning / face options when those later tasks run) |
| `(0028,0303) Longitudinal Temporal Information Modified` | `MODIFIED` when a date-delta strategy runs |
| `(0012,0052)` / `(0012,0053)` (rebase path) | `Longitudinal Temporal Offset From Event` and `Longitudinal Temporal Event Type = REGISTRATION` when `@rebasedate` / registration rebase runs |

Script `@always()…` rules may also **create** missing non-sequence elements with a fixed literal. Custom scripts can insert additional fixed values the same way.

### Transfer Syntaxes for Encrypted Attributes Data Set

**Not applicable.** Encrypted Attributes Data Sets are not created, so no Transfer Syntax is claimed for encoding or decoding them.

(General DICOM read/write for ordinary SOP Instances uses the Transfer Syntaxes supported by the application’s DICOM libraries for import, local store, and Send — that is outside the Encrypted Attributes requirement in E.1.3.)

### Which Options are supported

| Option (CID 7050) | Supported? | When it applies |
| --- | --- | --- |
| Basic Application Confidentiality Profile (113100) | **Yes** (always) | Import |
| Clean Pixel Data (113101) | **Yes** | After import — Embedded PHI / Remove Burnt-in Text (requires models) |
| Clean Recognizable Visual Features (113102) | **Yes** | After import — Blur Face on eligible head CT/MR (requires models) |
| Clean Graphics (113103) | **Selectable only** | Intent only — see note below |
| Clean Structured Content (113104) | **Yes** | After import — Report Text Review / AI Batch on SR/PDF (requires models) |
| Clean Descriptors (113105) | **Yes** | After import — metadata text cleaning (requires models) |
| Retain Longitudinal Temporal Information Full Dates (113106) | **Yes** | Import (mutually exclusive with Modified Dates) |
| Retain Longitudinal Temporal Information Modified Dates (113107) | **Yes** | Import (default Retain preset) |
| Retain Patient Characteristics (113108) | **Yes** | Import |
| Retain Device Identity (113109) | **Yes** | Import |
| Retain UIDs (113110) | **Yes** | Import |
| Retain Safe Private (113111) | **Yes** | Import (TCIA private-tag KB) |
| Retain Institution Identity (113112) | **Yes** | Import |

Presets and UI: [Create a project — De-identification options](05-create-project/index.md#2-de-identification-options). Option meanings: [De-identification protocol](deidentification-protocol.md#de-identification-options-ingest).

!!! note "Why Clean Graphics is not executed"
    The DICOM **Clean Graphics** option targets **non-text** burned-in graphics in pixels (logos, rulers, decorative marks) beyond ordinary curve/overlay groups. Under Basic Profile, this product already **removes curve and overlay groups** at import. Remaining non-text burned-in graphics are uncommon in modern clinical research archives (most residual pixel PHI is **text**, handled by Clean Pixel Data / Embedded PHI). Building a separate detector/scrubber for that legacy edge case has not been prioritized; selecting Clean Graphics only records project intent and does **not** stamp or run a processing task.

### Additional restrictions

- **No Encrypted Attributes / public-key re-identification path** — no key sizes or cipher suites are claimed.
- **Clean\* pixel, report, descriptor, and face options** require installed on-device AI features; selecting them without models is blocked or offered as a download in the UI.
- **Custom CTP scripts** may be imported; unknown operands are rejected; all date rules must match the Study Date operand; recorded option codes are those you confirm after import inference.
- **Re-accepting de-identification options** on an existing project recompiles from the packaged default plus overlays and **discards** prior custom script edits; already-imported instances are not re-anonymized.
- **MIDI-B** scores are evidence for header review, not a substitute for institutional determination ([protocol](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b)).

!!! note "For compliance review"
    Have your privacy officer review this statement together with the project’s [de-identification options](05-create-project/index.md#2-de-identification-options), compiled script, and any [custom script edits](05-create-project/index.md#4-custom-script-edits). This manual is operational and standards documentation, not legal advice.
