# Anonymizer scripts

| Script | Role |
| --- | --- |
| `default-anonymizer.script` | Packaged base script; project scripts are compiled from this plus the selected de-identification options |

Edit the project script via Settings (or import a custom CTP script). Import rewrites common CTP operand aliases (`@keep()`, `@hashuid`, `@DATEINC`, …) to product forms; the keep table is validated with `validate_document` on every reload. Sequences are always walked; CTP “keep SQ without processing items” is not supported. Private tags are not in this script; Retain Safe Private uses the TCIA Private Tag KB under `assets/tcia_kb/`. CTP-style `XX` / `GGGGEEEE` wildcard rows are also omitted (this product has no wildcard matcher).

DATEINC for private-tag date ops: `controller/private_tags/dateinc.txt`.

## Basic Profile vs Table E.1-1

The packaged default script’s public-tag rules for the DICOM Basic Application Confidentiality Profile are aligned to [PS 3.15 Table E.1-1](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) using the committed extract `controller/script/e1_1_basic_profile.json`.

| E.1-1 Basic action | Script operand |
| --- | --- |
| `X` | `@remove()` |
| `Z` | `@empty()` |
| `D` | `@empty()` |
| `U` | `@uid` |
| Mixtures (e.g. `X/Z`, `Z/D`) | Prefer `X`, then `Z`, then `D`, then `U` |

**Product remaps kept when already present and legal under Z/D/U:** `@ptid`, `@acc`, `@hashdate`, `@uid`, and Patient’s Age `@round(this,5)`.

**Clean Descriptors deferrals** (stay `@keep` under Basic so Embedded PHI can scrub free text): Study Description, Series Description, Requested Series Description, Institutional Department Name, Image Comments.

Regenerate alignment:

```bash
uv run python -m prototyping.script.align_default_script_e1_1
```
