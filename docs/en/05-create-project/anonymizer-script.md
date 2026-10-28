# Anonymizer script (advanced)

[De-identification options](index.md#2-de-identification-options) compile the project script for most sites. Use this page to change individual tag rules, choose a date strategy, load a patient lookup table, or import a CTP `.script`.

## Open the editor

After the project exists: **File → Project Settings → Edit Anonymizer Script**.

The editor loads `{site_id}-anonymizer.script` next to `ProjectModel.json` in the project storage folder (the folder shown at the top of the **Dashboard**). The dialog **Script** line is that script file path. The packaged `default-anonymizer.script` is never overwritten.

Header status: option summary (**Basic**, **Retain**, or abbreviated selected options). **Custom** means the live script no longer matches a fresh compile of the stored options.

![Anonymizer Script Editor](shots/macos/AnonymizerScriptEditor.png)

## Views

| View | Contents |
| --- | --- |
| **Active** (default) | Rules that keep or transform the value (not `@remove()`). |
| **Removed** | Rules whose operation is `@remove()`. |
| **All** | Every rule in the script. |

**Search** and the toolbar **Operand** filter apply within the current view.

## Change a rule {#4-custom-script-edits}

1. Select a row.
2. Inspect operands with the toolbar **Operand** filter or the detail **Operand** control — **How this operand works** updates immediately; the rule does not change until **Apply**.
3. If the operand requires a parameter, **Apply** prompts for it (see [Operands](#operands)). **Change parameter** edits the parameter on a rule that already uses that operand.
4. **@remove()** then **Apply** moves the tag out of **Active** (the rule remains in the script).

## Operand catalog {#operands}

Supported operations match the script editor catalog and ingest walk. Parameters are prompted on **Apply** when required. Date-delta operations on date fields must use the same operation as **StudyDate** (the editor offers one-click alignment).

| Operand (script text) | Parameter | Behavior |
| --- | --- | --- |
| `@keep` | — | Leave the value unchanged. Kept free-text may still be scanned by Embedded PHI / report NER. |
| `@safe()` | — | Product extension (not CTP): leave the value unchanged and exclude it from Embedded PHI / PseudoPHI bulk NER. Use for retained technical strings that must not be NER-scrubbed. |
| `@remove()` | — | Delete the tag from the anonymized dataset. |
| `@empty()` | — | Keep the tag present with an empty value. |
| `@uid` | — | Replace with a stable anonymized UID. Same original UID → same anonymized UID within the project (referential integrity). |
| `@ptid` | — | Replace with the project's anonymized Patient ID for this patient. |
| `@acc` | — | Replace with the anonymized Accession Number for this study when assigned. Empty source stays empty. |
| `@hashdate` | — | Shift date/datetime by a stable per-patient day offset derived from the PHI Patient ID. Intervals between that patient's studies are preserved. Sets `(0028,0303) LongitudinalTemporalInformationModified = MODIFIED` when any date-delta runs (records code 113107 when Modified Dates is selected). |
| `@lookup(this,ptid)` | — | Replace with the anonymized Patient ID from the project patient lookup table (`ptid/` rows in CTP `.properties`). If the table is not loaded, **Apply** opens **Load Patient Lookup Table**. |
| `@lookup(this,dateoffset)` | — | Apply the per-patient day offset from the lookup table (`dateoffset/` rows). If those rows are not loaded, **Apply** opens **Load Patient Lookup Table**. |
| `@incrementdate(this,n)` | **`n`**: signed integer day offset (trial-wide DATEINC). Positive moves dates later; negative earlier. Confirming applies the same `@incrementdate(this,n)` to every date-delta field in the script (listed in the prompt). | Fixed day shift for every patient. Intervals between a patient's studies are preserved. |
| `@rebasedate(this,origin)` | **`origin`**: epoch start as `YYYYMMDD` (eight digits; default `19600101`). | TCIA/NCTN rebase: anonymized date = `origin + (real date − basedate)`. Requires `basedate/<PatientID>=YYYYMMDD` in the lookup table. Writes `(0012,0052)` / `(0012,0053)=REGISTRATION` from PHI StudyDate − basedate. If basedates are not loaded, **Apply** opens **Load Patient Lookup Table** first. |
| `@round(this,n)` | **`n`**: integer ≥ 1, age band width in whole years. Ages round **down** to the nearest multiple of `n` (AS VR). | Coarsen Patient Age. Width `5`: `023Y` → `020Y`, `029Y` → `025Y`. |
| `@always()text` | **`text`**: non-empty literal replacement (must not start with `@`). Stored as `@always()YES`. Bare non-`@` literals such as `YES` in older scripts are the same operand. | Set the element to a fixed value; create the element if missing. |
| `@process()` | — | Keep the sequence (`SQ`) wrapper and recursively apply script rules to items inside it. |

Toolbar **Operand** filter **All** shows every rule in the view; choosing a specific operand filters the list and updates help without assigning until **Apply**.

## Add a missing tag

**Add from Dictionary** (bottom bar) lists DICOM dictionary tags absent from the script. **Add** inserts one rule with default `@keep`. The button is hidden when the script already covers the dictionary.

## Save

| Control | Effect |
| --- | --- |
| **Accept** | Validate operands; write `{site_id}-anonymizer.script` in the project storage folder; reload live anonymizer rules; keep the project pointed at that file. |
| **Revert** | Reload the script file from disk; discard unsaved edits. |
| **Cancel** | Close without saving. |

!!! note "Options vs custom edits"
    Accepting new [de-identification options](index.md#2-de-identification-options) recompiles from the packaged default plus overlays and **discards** custom script edits. Already-stored instances are not re-anonymized.

## Patient lookup table and dates {#5-patient-lookup-table-and-dates}

### Longitudinal dates {#longitudinal-dates-tcia-style}

| Strategy | Operand | Requirement |
| --- | --- | --- |
| Per-patient hash | `@hashdate` | Default compiled script; no lookup table. |
| Per-patient lookup offset | `@lookup(this,dateoffset)` | `dateoffset/` rows in the lookup `.properties`. |
| Trial-wide offset | `@incrementdate(this,n)` | Parameter `n` (DATEINC); applied to all date-delta fields. |
| Epoch rebase | `@rebasedate(this,origin)` | `basedate/` rows; parameter `origin` (`YYYYMMDD`). |

All four preserve intervals between a patient's studies and set Longitudinal Temporal Information Modified as described under `@hashdate` above. Deterministic UID/date/accession caveats: [De-identification protocol](../deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

### Patient Lookup Table {#patient-lookup-table}

Open **Load Patient Lookup Table** by:

- **Apply** on `@lookup(this,ptid)`, `@lookup(this,dateoffset)`, or `@rebasedate(this,origin)` when the required table (or `dateoffset` / `basedate` rows) is not loaded; or
- **Load Lookup Table** / **Replace Lookup Table** beside the detail **Operand** control on a lookup-dependent rule.

![Load Patient Lookup Table](shots/macos/LookupTable.png)

**Load Patient Lookup Table**:

1. **Browse…** to a CTP/TCIA `.properties` file.
2. Confirm patient and date-offset counts and the listed **script changes** (`@ptid` → `@lookup(this,ptid)`, `@hashdate` → `@lookup(this,dateoffset)`, and matching date fields).
3. **Accept** stores a project-private copy of the table, rewrites those rules, and enables runtime lookup. **Cancel** leaves the script unchanged.

`.properties` keys:

```text
ptid/<PHI-PatientID>=<anonymized-PatientID>
dateoffset/<PHI-PatientID>=<signed-integer-days>
basedate/<PHI-PatientID>=YYYYMMDD
```

`ptid/` alone is valid. `dateoffset/` enables `@lookup(this,dateoffset)`. `basedate/` enables `@rebasedate(this,origin)`.

!!! note "Lookup after files are stored"
    Loading a lookup table does **not** re-anonymize instances already in the project. Patients already in the project continue without a table row. **New** files whose PHI Patient ID is absent from the table are quarantined as **Lookup_Miss** and are not stored.

## Import a CTP script

**Import…** loads a custom `.script` file (not a lookup `.properties`). Unknown operands are rejected. Date rules must match the StudyDate operation (one-click fix available). On **Accept**, confirm which de-identification options to record for that script (prefilled from its rules).

## If it fails

- **Accept** rejected → fix unsupported `@…` operands listed in the error. Empty `@always()` is invalid; supply non-empty `text`. Bare non-`@` literals are accepted as fixed values (`ALWAYS`).

## See also

- [Create a project](index.md) — how options compile `{site_id}-anonymizer.script`
- [De-identification protocol](../deidentification-protocol.md)
- [DICOM Conformance Statement](../dicom-conformance-statement.md)
