# RadLex and harmonized CT series descriptions

This note documents external terminology sources relevant to FALCON **Harmonize Description** in Series View. Harmonize writes a proposed value to DICOM **Series Description** `(0008,103E)` after inference.

There is no single RadLex document titled “harmonization rules for CT series description.” Procedure-level naming (LOINC/RSNA Radiology Playbook) and series-level naming (RadLex Series Playbook / Study Series) are related but not identical.

## What this application produces

**Harmonize Description** (Series View) combines:

1. **TotalSegmentator (`tseg`)** — anatomic analysis from segmented organ volumes and HU statistics (primary for regions and contrast).
2. **FALCON** — predictive ResNet9 classifier (fallback when anatomy analysis fails).

The harmonized label uses RadLex Playbook+ multi-region syntax in `tseg/radlex.py`:

```text
{Modality} {Body regions joined by +} {With Contrast | Without Contrast}
```

Examples:

- `CT Chest With Contrast`
- `CT Head+Neck Without Contrast`
- `CT Chest+Abdomen With Contrast`

| Internal region | Playbook+ label in description |
| --------------- | ------------------------------ |
| `Head`          | Head+Neck                      |
| `Chest`         | Chest                          |
| `Abdomen`       | Abdomen                        |

Multi-region volumes use `+` between regions (e.g. `Chest+Abdomen`). Contrast is derived from organ median HU phase analysis (native → Without; arterial/portal → With).

FALCON alone (when used as fallback) still uses its own formatter in `predict._format_radlex_series_description()`:

```text
{Modality} {Body part} {With Contrast | Without Contrast}
```

FALCON body-part labels (`HeadNeck` → `Head Neck`) differ from the Playbook+ harmonized form (`Head+Neck`).

---

## CT series-level naming (closest to Series Description)

RSNA **Study Series / RadLex Series Playbook** targets vendor-neutral **imaging-series** names for DICOM (including CT), i.e. closer to `SeriesDescription` than to radiology order codes alone.

| Resource | URL |
| -------- | --- |
| Project repository (overview and pointers) | <https://github.com/RSNA/Study-Series> |
| CT naming convention rules (working document cited by RSNA) | <https://docs.google.com/document/d/13gaxnY99JLuoN3M_CI7rtiXh3uWmDnyBmTKm3BE_8_o/edit?usp=sharing> |

The Study-Series repo references an RSNA landing page (`…/radlex-series-playbook`); that URL may be unavailable—the GitHub repo and Google doc are the stable entry points.

Feedback contacts listed in the Study-Series README: ross.w.filice@medstar.net, Audrey.verde@duke.edu, vgeisendorfer@rsna.org.

---

## Procedure / orderable naming (LOINC/RSNA Radiology Playbook)

The harmonized **LOINC/RSNA Radiology Playbook** defines the attribute model and syntax for standard procedure names: modality, anatomic location, pharmaceutical (contrast), view, timing, and related attributes. It is framed around **orderables**, not DICOM series tags, but it is the main specification for how to compose a standard CT procedure name from parts.

| Resource | URL |
| -------- | --- |
| **LOINC/RSNA Radiology Playbook User Guide** (primary: semantics and syntax) | <https://loinc.org/kb/users-guide/loinc-rsna-radiology-playbook-user-guide/> |
| Modality (CT, MR, combinations, subtypes) | Same guide — Modality section |
| Anatomic location / body region | Same guide — Anatomic Location section |
| Contrast and other agents | Same guide — Pharmaceutical section (e.g. `WO contrast IV`, `W contrast IV`) |
| LOINC downloads and related user guides | <https://loinc.org/download/loinc-users-guide> |

Legacy / supplementary material (RPID model, harmonization with LOINC, examples):

| Resource | URL |
| -------- | --- |
| RadLex Playbook User Guide 2.5 (PDF) | <https://playbook.radlex.org/playbook-user-guide-2_5.pdf> |
| Search canonical Playbook terms | <https://playbook.radlex.org/playbook/SearchRadlexAction> |

Background:

| Resource | URL |
| -------- | --- |
| RSNA RadLex and Playbook overview | <https://www.rsna.org/practice-tools/data-tools-and-standards/radlex-radiology-lexicon> |
| Mapping institution-specific descriptions to Playbook entries | <https://pmc.ncbi.nlm.nih.gov/articles/PMC4026460/> |

RadLex Playbook identifiers (RPID) are being superseded by LOINC-format codes for new terms; new adopters are encouraged to use LOINC-format codes (see Playbook user guides).

---

## Alignment and gaps vs full Playbook compliance

| Aspect | This application | Full LOINC/RSNA Playbook |
| ------ | ---------------- | ------------------------ |
| Target field | DICOM `SeriesDescription` | Orderables / registry / enterprise procedure codes |
| Modality | `CT` literal | Formal Modality attribute (DICOM-aligned codes, subtypes) |
| Body region | Three FALCON regions only | Anatomic Location from RadLex hierarchy; multiple regions possible |
| Contrast | `With Contrast` / `Without Contrast` | Pharmaceutical attribute (e.g. `WO contrast IV`, combined phases) |
| Identifiers | None written to DICOM | LOINC code and/or legacy RPID |

Strict Playbook compliance would map inference results to a specific **LOINC code** or **RPID** via Playbook tables, not only a free-text template.

Example Playbook-style contrast phrasing (from the LOINC/RSNA guide) differs from our labels:

```text
WO contrast IV          # without IV contrast
W contrast IV           # with IV contrast
WO & W contrast IV      # without then with
```

---

## Suggested reading order

1. **Series-level CT rules:** [Study-Series](https://github.com/RSNA/Study-Series) → [CT naming rules doc](https://docs.google.com/document/d/13gaxnY99JLuoN3M_CI7rtiXh3uWmDnyBmTKm3BE_8_o/edit?usp=sharing)
2. **Composable procedure semantics:** [LOINC/RSNA Radiology Playbook User Guide](https://loinc.org/kb/users-guide/loinc-rsna-radiology-playbook-user-guide/)
3. **Lookup canonical terms:** [Playbook search](https://playbook.radlex.org/playbook/SearchRadlexAction)

---

## Implementation references in this repo

- FALCON upstream attribution, models, and publication: [README.md](README.md)
- FALCON description formatter: `src/anonymizer/controller/falcon/predict.py`
- TotalSegmentator anatomy analysis: `src/anonymizer/controller/tseg/segment.py` — `analyze_series()`, `TS_result`
- Playbook+ harmonized formatter: `src/anonymizer/controller/tseg/radlex.py`
- Harmonize merge logic: `src/anonymizer/controller/harmonize.py` — `harmonize_series()`, `HarmonizedResult`
- Series View UI: `src/anonymizer/view/series.py` — Harmonize Description, apply to `(0008,103E)` via `apply_series_description()`
