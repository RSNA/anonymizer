# Anonymization policy assets

| File | Role |
| --- | --- |
| `tcia_table1_ctp_ops.csv` | TCIA Overview Table 1 mirror (reference / drift diff only) |
| `clinical_dateinc.txt` | Trial-wide DATEINC days for Embedded PHI private date ops |
| `TCIAPrivateTagKB-02-01-2024-formatted.csv` | Official TCIA Private Tag KB |
| `tcia_private_tag_kb.csv` | Flattened private dispositions (`k`/`d`/`h`/`o`/`oi` + `vr`) |

**Clinical public-tag policy** is maintained in
[`../scripts/clinical-anonymizer.script`](../scripts/clinical-anonymizer.script)
(edit the script directly). It was seeded once from the stock default script +
Table 1 CSV, then fine-tuned (gold retention, `@safe()`, etc.).

## TCIA sources

- [Submission and De-identification Overview](https://www.cancerimagingarchive.net/submission-and-de-identification-overview/) (Table 1)
- Private KB download:  
  https://wiki.cancerimagingarchive.net/download/attachments/3539047/TCIAPrivateTagKB-02-01-2024-formatted.csv?version=2&modificationDate=1707174689263&api=v2

## Table 1 reference map

| TCIA CTP cell | Product operand |
| --- | --- |
| `@remove()` / `removed` | `@remove()` |
| `@keep()` | keep (empty) or `@safe()` |
| `@empty()` | `@empty()` |
| `@process()` | `@process()` |
| `@incrementdate(this,@DATEINC)` | `@incrementdate(this,N)` (`clinical_dateinc.txt`) |
| `@hashuid(@UIDROOT,this)` | `@uid` |
| `LOOKUP(...,ptid)` | `@ptid` |

List divergences (not a correctness gate):

```bash
uv run python src/anonymizer/assets/scripts/diff_clinical_table1.py
```

### Safe keep (`@safe()`)

Retain the value like keep, but **do not** send the field to bulk NER.
Product-only (not a CTP operand). Set on equipment / model strings in the
clinical script (e.g. ManufacturerModelName). Private creator IDs are skipped
from NER by tag class.

### Fine-tunes vs the Table 1 CSV

Examples already in the script (see `diff_clinical_table1.py` output):

- Keep attributes DeIdentified gold retains that the CSV marks `@remove()`
  (Occupation, ImageComments, DerivationDescription, PatientComments,
  PatientState, Scheduled Procedure Step ID).
- `@remove()` Clinical Trial Time Point Description `(0012,0051)` despite CSV keep.
- `@remove()` SecondaryCaptureDeviceID (no Retain Device Identity).
  DateOfLastCalibration: `@incrementdate` (MIDI-B answer key `date_shifted`).
  TimeOfLastCalibration kept. DateOfLastDetectorCalibration: `@remove()`
  (Table 1 / PseudoPHI gold empties; TimeOfLastDetectorCalibration kept).
- `@safe()` on retained manufacturer / model / software version strings,
  CodingSchemeDesignator, and RescaleType (avoid NER over-blank of scheme IDs /
  ``US``).

Public tags **absent** from Table 1 stay kept (Posda-style deferral from the
default script’s `@remove()`/`@empty()`).

## Private KB (Retain Safe Private) — Embedded PHI, not Clinical ingest

**Strict ingest:** all private tags wiped (`remove_private_tags`) — fast.

**Clinical ingest:** private tags are **left untouched** on the anonymize walk.  
TCIA Private KB dispositions are applied later by Embedded PHI
``process_private_tags_tcia()`` (creator-aware). The clinical script does **not**
contain private-tag rows.

| Disposition | Meaning (for Embedded PHI) |
| --- | --- |
| `k` | keep |
| `d` | remove |
| `h` | `@uid` if VR UI / UID note, else remove |
| `o` / `oi` | DATEINC if DA/DT/TM (or Date/Time note), else remove |

**Flatten / XX collapse rule** (``ACTION_PRIORITY`` in ``tcia_kb``): official KB
often lists the same ``(group, creator, elem)`` once per VR (typed = `k`/`h`,
`UN` = `d`). Under Retain Safe Private, **keep/transform beats delete**
(`o`/`oi` > `h` > `k` > `d`). MIDI-B answer-key overrides (e.g. GEMS_PETD
`0009XX0F` Scan Description → `k`) live in `convert_tcia_private_kb.py`.

```bash
uv run python src/anonymizer/assets/anonymization_policy/convert_tcia_private_kb.py
uv run python src/anonymizer/assets/scripts/diff_clinical_table1.py
```
