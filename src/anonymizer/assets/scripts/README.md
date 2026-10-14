# Anonymizer scripts

| Script | Policy |
| --- | --- |
| `default-anonymizer.script` | **Strict** (baseline) |
| `clinical-anonymizer.script` | **Clinical** — maintained artifact (public tags) |

Edit `clinical-anonymizer.script` directly for Clinical public-tag policy.
Private tags are not in this script; Embedded PHI applies the TCIA Private Tag KB.

## Table 1 reference diff

Optional: list where the clinical script diverges from the website Table 1 CSV
(reference only — fine-tunes are expected):

```bash
uv run python src/anonymizer/assets/scripts/diff_clinical_table1.py
```

Policy notes and DATEINC / private KB sources:
`assets/anonymization_policy/SOURCE.md`.
