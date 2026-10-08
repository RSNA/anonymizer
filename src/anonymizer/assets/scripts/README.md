# Anonymizer scripts

| Script | Policy |
| --- | --- |
| `default-anonymizer.script` | **Strict** (unchanged baseline) |
| `clinical-anonymizer.script` | **Clinical** (compiler output) |

## Compile Clinical script

```bash
uv run python src/anonymizer/assets/scripts/compile_clinical_script.py
uv run python src/anonymizer/assets/scripts/compile_clinical_script.py --check
```

Inputs live under `assets/anonymization_policy/` (`clinical_text_keep_tags.txt`, `tcia_private_tag_kb.csv`). Re-run and commit when those change.
