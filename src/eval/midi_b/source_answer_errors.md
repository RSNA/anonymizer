# MIDI-B: source DICOM vs answer-key discrepancies

Evidence for enquiry with TCIA / MIDI-B maintainers. Measured on:

- Full Synthetic **Validation** scoring run `validation_20261101T120658Z_full`
  (`MIDI-B-Answer-Key-Validation.db`) against
  `…/Synthetic Validation/manifest-1740445452889/MIDI-B-Synthetic-Validation`
- Full Synthetic **Test** scoring run `test_20261101T174432Z_full`
  (`MIDI-B-Answer-Key-Test.db`) against
  `…/Synthetic Test/manifest-1740627604844/MIDI-B-Synthetic-Test`

These are **not** Clean Descriptors / Embedded PHI failures (except where noted). They are
mismatches between (1) what is in the published synthetic source, (2) TCIA Private Tag
Knowledge Base (PTKB) / de-identification options we apply, and (3) what the answer key
scores (`<text_retained>`, `<tag_retained>`, …).

**Validation `<text_retained>` scale:** 55,431 fails overall. Of those, 53,444 had an empty
submitted value while the answer expected a non-empty value. Against **source** (not
submitted output):

| Bucket | Rows | Meaning |
|---|---:|---|
| Source empty / missing, answer non-empty | **39,351** | Answer asks for a value the source does not have (almost all GEMS) |
| Source already equals answer | **14,093** | Source correct; de-id removed or never emitted the value (almost all UCSF QC Sequence) |

**Test `<tag_retained>` scale:** 1,736 fails / 1,325,259 checks (see §3).

---

## 1. GEMS_PETD_01 numeric private tags — empty in source, non-empty in answer

### Summary

Private creator `GEMS_PETD_01`, group `0009`. Several SL/FL elements are present in the
synthetic source with **no value** (`None` / empty), while the answer key’s
`<text_retained>` checks expect integer/float text such as `0`, `1`, `2`, `3`, `28`.

TCIA PTKB marks these tags **KEEP**. Our pipeline keeps the empty elements. The official
validator still fails retain because `file_value` is empty and `answer_value` is not.

**~39,334** discrepancy rows in the full run (17 patients, 8,226 instances).

### Tags involved (element suffix in PTKB private notation)

| Answer `tag_ds` | PTKB name (approx.) | Fail count | PTKB action |
|---|---|---:|---|
| `(0009,"GEMS_PETD_01",b8)` | IR Loop Filt Param | 8,226 | KEEP |
| `(0009,"GEMS_PETD_01",b2)` | IR Num Iterations | 6,016 | KEEP |
| `(0009,"GEMS_PETD_01",b3)` | IR Num Subsets | 6,016 | KEEP |
| `(0009,"GEMS_PETD_01",b6)` | IR Loop Filter | 6,016 | KEEP |
| `(0009,"GEMS_PETD_01",ba)` | Post Filter | 6,016 | KEEP |
| `(0009,"GEMS_PETD_01",c6)` | seg_qc_parm | 2,538 | KEEP |
| `(0009,"GEMS_PETD_01",e9)` | acq_bin_dur_percent | 2,538 | KEEP |
| plus `9d`, `b5`, `bc`, `be`, `c1`, `c4` | (same pattern) | 328 each | KEEP |

Answer values observed for these fails: `0`, `1`, `2`, `3`, `4`, `21`, `28`, `30`
(no empty answers in this set).

### Concrete reproduce

| Field | Value |
|---|---|
| Source PatientID | `8810956335` |
| Source SOP Instance UID | `3.5.673.1.1.2288579.7.086.2184911347333325627` |
| Source file (under synthetic root) | `8810956335/…/1-66.dcm` |
| Anonymized PatientID (our mapping) | `990001-000115` |
| Anonymized SOP | `1.2.826.0.1.3680043.10.474.2.990001.2.73463680521944568175114476` |

For `(0009,10B2)` / answer tag `(0009,"GEMS_PETD_01",b2)` (“IR Num Iterations”):

- **Source:** element present, VR `SL`, value empty (`None`)
- **De-identified output:** same — present, empty (KEEP)
- **Answer key:** `<text_retained>`, `answer_value` = `2`

Same emptiness in source for `b3`, `b6`, `b8`, `ba` on that instance.

### Questions for TCIA

1. Should the Validation answer key expect empty / omit `<text_retained>` when the
   synthetic source element is empty?
2. Or should the synthetic source be corrected to contain the numeric values currently
   stored as `answer_value`?
3. Is PTKB KEEP-with-empty the intended curation outcome for these GEMS PET IR parameters?

---

## 2. UCSF BIRP QC Sequence — PTKB removes parent; answer retains children

### Summary

Private creator `UCSF BIRP PRIVATE CREATOR 011710xx`, group `0117`.

- PTKB: **`(0117,xx24)` QC Sequence → REMOVE** (SQ)
- PTKB: nested **`c0`–`c3`** (QC Type / Factor / value / meaning) → **KEEP**
- Validation answer key: `<text_retained>` on those nested paths with values such as
  `SCORE`, `Fat Suppression`, `3.0`, `GOOD`, …

Safe Private applies `@remove()` to the parent sequence. Nested KEEP entries never get a
chance to survive. Top-level siblings `c5` / `c6` (KEEP) remain.

**~13,686** `<text_retained>` fails in the full run (8 patients, 926 instances). On every
checked row, the **source already contained the answer text**; only the de-identified
object lacked the sequence.

### PTKB entries (canonical)

Creator key `ucsf birp private creator 011710xx`, group `279` (`0x0117`):

| Suffix (dec / hex) | Note | Action |
|---|---|---|
| 36 / `0x24` | QC Sequence | **REMOVE** |
| 192 / `0xC0` | QC Sequence:QC Type | KEEP |
| 193 / `0xC1` | QC Sequence:QC Factor | KEEP |
| 194 / `0xC2` | QC Sequence:QC value | KEEP |
| 195 / `0xC3` | QC Sequence:QC meaning | KEEP |
| 196 / `0xC4` | QC Sequence:QC comment | REMOVE |
| 197 / `0xC5` | Protocol compliance | KEEP (top-level; survives) |
| 198 / `0xC6` | Protocol non-compliance reasons | KEEP (top-level; survives) |

### Concrete reproduce

| Field | Value |
|---|---|
| Source PatientID | `4953814140` |
| Source SOP Instance UID | `1.3.241.0.0.3328322.7.935.2005384749146060566` |
| Source file | `4953814140/…/1-182.dcm` |
| Anonymized PatientID | `990001-000067` |
| Anonymized SOP | `1.2.826.0.1.3680043.10.474.2.990001.2.51858488774734239380103003` |

**Source `(0117,1024)`:** SQ length 4. Item `[0]` includes:

- `(0117,10C0)` = `SCORE`
- `(0117,10C1)` = `Fat Suppression`
- `(0117,10C2)` = `3.0`
- `(0117,10C3)` = `GOOD`

**Answer path (item 0, c0):**  
`<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",24)>[<0000>]<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",c0)>`  
→ `<text_retained>`, expected `SCORE`.

**After Safe Private (PTKB):** creator `(0117,0010)` and top-level `c5`/`c6` present;
`(0117,1024)` QC Sequence **absent**.

Note: the answer key names the parent with private-creator notation
`(0117,"…",24)`; pydicom’s indexer often emits the same sequence as `(0117,1024)` when
`private_creator` is not attached on the SQ element. Values still match under the numeric
parent path.

### Questions for TCIA

1. Is QC Sequence (`xx24`) intentionally REMOVE in PTKB even though nested QC fields are
   KEEP and the MIDI Validation answer key scores them as retained?
2. Should PTKB change `xx24` to KEEP (and keep removing only `xxC4` comment), or should
   the answer key drop / flip those nested retain checks?
3. How should implementations reconcile parent-REMOVE vs child-KEEP for private sequences?

---

## 3. Public tags — `<tag_retained>` when attribute is absent in source

### Scorer meaning

- **`<tag_retained>`:** tag must be **present** in the submitted file (existence only; value
  not compared).
- **`<text_retained>`:** tag present **and** text matches expected `action_text`.

`@keep` in the anonymizer script means “leave the attribute if it is already in the
source.” It does **not** create missing tags.

### Summary (Test run `test_20261101T174432Z_full`)

**1,736** `<tag_retained>` fails. For every `@keep` tag in this set, sampled failing
instances had the attribute **absent in the synthetic source** and **absent in the
de-identified public output** — nothing removed them; they were never present. The Test
answer key still requires `<tag_retained>`.

Same pattern appeared on Validation (e.g. Position Reference Indicator / KVP /
Acquisition Number among `<tag_retained>` fails there).

### Fail counts by tag (Test)

| Tag | Name | Fails | Compiled script op | In source (sampled fails)? | In public? |
|---|---|---:|---|---|---|
| `(0020,1040)` | Position Reference Indicator | 894 | `@keep` | No | No |
| `(0018,0060)` | KVP | 349 | `@keep` | No | No |
| `(0020,0012)` | Acquisition Number | 349 | `@keep` | No | No |
| `(2050,0020)` | Presentation LUT Shape | 39 | `@keep` | No | No |
| `(0008,0068)` | Presentation Intent Type | 36 | `@keep` | No | No |
| `(0018,7004)` | Detector Type | 23 | `@keep` | No | No |
| `(0018,1164)` | Imager Pixel Spacing | 3 | `@keep` | No | No |
| `(0020,0062)` | Image Laterality | 3 | `@keep` | No | No |
| `(0028,0301)` | Burned In Annotation | 2 | `@keep` | No | No |
| `(0028,1040)` | Pixel Intensity Relationship | 2 | `@keep` | No | No |
| `(0028,1041)` | Pixel Intensity Relationship Sign | 2 | `@keep` | No | No |
| `(0028,1054)` | Rescale Type | 2 | `@keep` | No | No |
| `(0018,1000)` | Device Serial Number | 32 | `@remove()` | **Yes** | **No** |

Sampling: up to 12 distinct failing SOPs per tag (all available when fewer).

These `@keep` tags are generally **not** listed in Retain TCIA Research
(`tcia_research_operands.json`) because Basic does not strip them — the base script
already keeps them. Absence from that catalog is expected and unrelated to the miss.

### Exception (not a source/answer mismatch): Device Serial Number

`(0018,1000)` is Basic `X/Z/D`. With **Retain Device Identity** off (MIDI-B / TCIA
practice; manufacturer/model/software kept via Retain TCIA Research `@safe()` instead),
compile leaves serial as `@remove()`. Source has the tag; we remove it. Answer
`<tag_retained>` then fails (**32** Test rows). Turning Retain Device Identity on would
keep serial; documented MIDI-B setup leaves it off.

### Concrete reproduce (`@keep` / absent in source)

| Field | Value |
|---|---|
| Split | Synthetic Test |
| Source PatientID | `402272604` |
| Source SOP | `…` (mapped from anon below) |
| Source file | `402272604/…/1-193.dcm` |
| Anonymized PatientID | `990001-000237` |
| Tag | `(0020,1040)` Position Reference Indicator |
| Source | **ABSENT** |
| Public | **ABSENT** |
| Answer | `<tag_retained>` |

KVP / Acquisition Number example (same SOP pair for both tags): source patient
`2435957512`, anon `990001-000130` — both tags absent in source and public; answer
`<tag_retained>`.

### Questions for TCIA

1. Should `<tag_retained>` rows be omitted (or flipped) when the published synthetic
   source does not contain the attribute?
2. Or should the synthetic source be corrected to include those attributes?
3. For Device Serial Number: is `<tag_retained>` intentional while Retain Device Identity
   is expected off for scoring?

---

## 4. Synthetic source vs answer key vs MIDI-B curated (sample table)

One failing discrepancy row per anomaly tag (first hit in the official participant
discrepancy CSV). Synthetic and curated instances are paired by **PixelData / decoded
pixel MD5** (same method as early prototyping). Curated roots:

- Test: `Curated Test/MIDI-B-Curated-Test`
- Validation: `Curated Validation/MIDI-B-Curated-Validation`

Machine-readable rows: `.midi_b_runs/source_answer_curated_compare.json`.

Legend: **EMPTY** = tag present, no value; **ABSENT** = tag not in dataset;
**NO_DIGEST_MATCH** = no pixel-digest pair (often non-pixel / SR-like); curated
**ABSENT(parent)** = QC Sequence SQ missing.

### GEMS_PETD_01 (`<text_retained>`, Synthetic Test)

| Tag | Answer key | Synthetic source | MIDI-B curated |
|---|---|---|---|
| `(0009,"GEMS_PETD_01",b8)` | `0` | EMPTY | **`0`** (filled) |
| `(0009,"GEMS_PETD_01",b2)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",b3)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",b6)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",ba)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",c6)` | `0` | EMPTY | **`0`** (filled) |
| `(0009,"GEMS_PETD_01",e9)` | `0` | EMPTY | **`0`** (filled) |
| `(0009,"GEMS_PETD_01",9d)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",b5)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",bc)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",be)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",c1)` | `0` | EMPTY | ABSENT |
| `(0009,"GEMS_PETD_01",c4)` | `0` | EMPTY | ABSENT |

**Read:** Answer expects a numeric string. Source is empty. Curated sometimes **invents**
the same integer (`b8`/`c6`/`e9` → `0`); for other suffixes curated **drops** the empty
tag. Neither curated behavior matches “leave empty source as-is,” and dropping the tag
still fails `<text_retained>` against the answer.

### Public `<tag_retained>` (Synthetic Test)

| Tag | Answer key | Synthetic source | MIDI-B curated |
|---|---|---|---|
| `(0020,1040)` Position Reference Indicator | present | ABSENT | ABSENT |
| `(0018,0060)` KVP | present | ABSENT | EMPTY (tag added, no value) |
| `(0020,0012)` Acquisition Number | present | ABSENT | EMPTY |
| `(2050,0020)` Presentation LUT Shape | present | ABSENT | ABSENT |
| `(0008,0068)` Presentation Intent Type | present | ABSENT | ABSENT |
| `(0018,1000)` Device Serial Number | present | `'ZCZCZESCZIM86'` | **ABSENT** (removed) |
| `(0018,7004)` Detector Type | present | ABSENT | EMPTY |
| `(0018,1164)` Imager Pixel Spacing | present | ABSENT | NO_DIGEST_MATCH |
| `(0020,0062)` Image Laterality | present | ABSENT | NO_DIGEST_MATCH |
| `(0028,0301)` Burned In Annotation | present | ABSENT | NO_DIGEST_MATCH |
| `(0028,1040)` Pixel Intensity Relationship | present | ABSENT | NO_DIGEST_MATCH |
| `(0028,1041)` Pixel Intensity Relationship Sign | present | ABSENT | NO_DIGEST_MATCH |
| `(0028,1054)` Rescale Type | present | ABSENT | NO_DIGEST_MATCH |

**Read:** For most `@keep` tags, source and curated both lack a real value (ABSENT or
EMPTY) while the answer requires presence. Device Serial Number is present in source and
**removed in curated** (aligns with Retain Device Identity off / Basic remove).

### UCSF BIRP QC Sequence nested (`<text_retained>`, Synthetic Validation)

| Tag (item 0) | Answer key | Synthetic source | MIDI-B curated |
|---|---|---|---|
| `…,24` / `…,c0` QC Type | `SCORE` | `'SCORE'` | ABSENT(parent SQ removed) |
| `…,24` / `…,c1` QC Factor | `Fat Suppression` | `'Fat Suppression'` | ABSENT(parent) |
| `…,24` / `…,c2` QC value | `3.0` | `'3.0'` | ABSENT(parent) |
| `…,24` / `…,c3` QC meaning | `GOOD` | `'GOOD'` | ABSENT(parent) |

**Read:** Source matches the answer. Curated removes the QC Sequence parent (same as
PTKB REMOVE on `xx24`). Official answer key still scores nested `<text_retained>`.

---

## 5. Suggested ask (short)

We observe systematic conflicts between published synthetic DICOMs / PTKB / curated
reference and answer keys:

1. **GEMS_PETD_01**: empty in synthetic source; answer non-empty; curated sometimes
   fills integers (`0`), sometimes drops the tag.
2. **UCSF BIRP QC Sequence**: source matches answer; curated and PTKB remove the parent
   SQ; answer still retains nested fields.
3. **Public `<tag_retained>`**: answer requires presence for tags absent (or empty) in
   synthetic source; curated usually also lacks them. Device Serial Number: present in
   source, removed in curated / by Basic without Retain Device Identity.

Please advise which artifact is authoritative for scoring: synthetic source, curated
reference, PTKB, de-id option baseline, or answer key.

### Evidence pointers

- Answer keys:
  - `Synthetic Validation/Answer Key/MIDI-B-Answer-Key-Validation.db`
  - `Synthetic Test/Answer Key/MIDI-B-Answer-Key-Test.db`
- Scorer: [CBIIT/MIDI_validation_script](https://github.com/CBIIT/MIDI_validation_script)
  (`validate_text_retained`: empty `file_value` → fail;
  `validate_tag_retained`: tag missing from file index → fail)
- PTKB mirror: `src/anonymizer/controller/private_tags/tcia_kb_data.py`
- Scorecards:
  - `.midi_b_runs/validation_20261101T120658Z_full/SCORECARD.md` (99.03%)
  - `.midi_b_runs/test_20261101T174432Z_full/SCORECARD.md` (99.08%)
- Source / answer / curated sample table: §4 and
  `.midi_b_runs/source_answer_curated_compare.json`
